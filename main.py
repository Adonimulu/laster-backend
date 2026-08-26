from fastapi import FastAPI, File, UploadFile, Query
import cloudscraper
from bs4 import BeautifulSoup
import uvicorn
import os
import re
import json
from urllib.parse import urlparse
import asyncio
from typing import Optional

app = FastAPI()

# Create a scraper that mimics a real browser more effectively
# We use cloudscraper to bypass simple bot detection
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome','platform': 'windows','mobile': False}
)

def extract_yandex_links(html):
    links = []

    # Strategy 1: Sites where image is found (HTML parsing)
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        href = a['href']
        if "yandex" not in href.lower() and href.startswith('http'):
            links.append(href)

    # Strategy 2: Look for 'data-state' which contains result items
    match = re.search(r'data-state="({.*?})"', html)
    if match:
        try:
            data_str = match.group(1).replace('&quot;', '"')
            urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', data_str)
            links.extend(urls)
        except:
            pass

    # Strategy 3: Pure Regex on the whole page for anything that looks like a source URL
    urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', html)
    links.extend(urls)

    return links

def extract_google_links(html):
    # Google Lens results are dynamic, but often contain the source URLs in the static HTML as well
    # for SEO or accessibility purposes.
    links = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', html)
    return links

def format_matches(raw_links, target_platform: Optional[str] = None):
    matches = []
    seen_urls = set()

    # Filter out common junk URLs from search engine pages
    blacklist = [
        'yandex', 'google', 'yastatic', 'captcha', 'feedback', 'market',
        'policies', 'support', 'accounts', 'bing', 'msn', 'schema.org',
        'w3.org', 'gstatic', 'doubleclick', 'analytics', 'facebook.com/tr/',
        'apple.com', 'microsoft.com', 'ampproject.org', 'wikipedia.org/wiki/Special'
    ]

    for url in raw_links:
        try:
            if not url.startswith('http'): continue

            # Remove tracking params
            clean_url = url.split('?')[0].rstrip('/')

            if clean_url in seen_urls: continue
            if any(x in clean_url.lower() for x in blacklist): continue

            parsed = urlparse(clean_url)
            domain = parsed.netloc.lower().replace('www.', '')

            # Skip very short or generic domains
            if len(domain.split('.')) < 2: continue

            platform_name = domain.split('.')[0].capitalize()

            # Map domains to social platforms
            if "instagram" in domain: platform_name = "Instagram"
            elif "facebook" in domain: platform_name = "Facebook"
            elif "tiktok" in domain: platform_name = "TikTok"
            elif "twitter" in domain or "x.com" in domain: platform_name = "X"
            elif "linkedin" in domain: platform_name = "LinkedIn"
            elif "pinterest" in domain: platform_name = "Pinterest"
            elif "youtube" in domain: platform_name = "YouTube"
            elif "snapchat" in domain: platform_name = "Snapchat"
            elif "telegram" in domain: platform_name = "Telegram"
            elif "reddit" in domain: platform_name = "Reddit"
            elif "vk.com" in domain: platform_name = "VK"
            elif "ok.ru" in domain: platform_name = "OK"

            # Filter if a specific platform was requested via query param
            if target_platform and target_platform.lower() not in platform_name.lower() and target_platform.lower() not in domain:
                continue

            matches.append({"platform": platform_name, "url": clean_url})
            seen_urls.add(clean_url)
        except:
            continue

    return matches

async def search_yandex(img_data):
    try:
        search_url = 'https://yandex.com/images/search'
        files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        params = {'rpt': 'imageview'}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://yandex.com/images/'
        }

        response = await asyncio.to_thread(scraper.post, search_url, params=params, files=files, headers=headers, timeout=25)
        return extract_yandex_links(response.text)
    except Exception as e:
        print(f"Yandex Search Error: {e}")
        return []

async def search_google(img_data):
    try:
        # Google Lens upload endpoint
        search_url = 'https://lens.google.com/upload'
        files = {'encoded_image': ('image.jpg', img_data, 'image/jpeg')}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
        }

        response = await asyncio.to_thread(scraper.post, search_url, files=files, headers=headers, timeout=25)
        return extract_google_links(response.text)
    except Exception as e:
        print(f"Google Lens Error: {e}")
        return []

@app.get("/")
def home():
    return {"status": "online", "engines": ["Yandex", "Google Lens"]}

@app.post("/search")
async def search(
    file: UploadFile = File(...),
    target_platform: Optional[str] = Query(None)
):
    try:
        img_data = await file.read()

        # Parallel search across engines
        results = await asyncio.gather(
            search_yandex(img_data),
            search_google(img_data)
        )

        all_links = results[0] + results[1]
        matches = format_matches(all_links, target_platform)

        # Return up to 50 results to keep the app responsive
        return {
            "status": "success",
            "matches": matches[:50],
            "total_raw_links": len(all_links) # Debugging info
        }

    except Exception as e:
        print(f"Search Execution Error: {e}")
        return {"status": "error", "message": "Search failed on server", "matches": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
