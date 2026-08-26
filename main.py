from fastapi import FastAPI, File, UploadFile, Query
import cloudscraper
from bs4 import BeautifulSoup
import uvicorn
import os
import re
import json
from urllib.parse import urlparse, quote
import asyncio
from typing import Optional

app = FastAPI()

# Enhanced scraper setup to handle Cloudflare and mimic a real browser
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)

def is_social_profile(url):
    """Checks if a URL belongs to a known social media platform."""
    if not url or not isinstance(url, str) or not url.startswith('http'):
        return False
    social_domains = [
        "instagram.com", "facebook.com", "fb.com", "twitter.com", "x.com",
        "linkedin.com", "tiktok.com", "pinterest.com", "youtube.com",
        "snapchat.com", "reddit.com", "t.me", "telegram.me", "vk.com", "ok.ru"
    ]
    domain = urlparse(url).netloc.lower()
    return any(social in domain for social in social_domains)

def extract_yandex_results(html):
    """Extracts both links and thumbnails from Yandex search results."""
    results = []
    soup = BeautifulSoup(html, 'html.parser')

    # Extract from JSON state (usually contains best quality mapping)
    match = re.search(r'data-state="({.*?})"', html)
    if match:
        try:
            data = json.loads(match.group(1).replace('&quot;', '"'))
            # Look for blocks with image and link info
            # This is a generic regex search within the JSON for mapping pairs
            # Usually found in 'serp-list' or 'rim-list' blocks
            items = re.findall(r'"url":"(http[^"]+)".*?"thumb":{"url":"(http[^"]+)"', str(data))
            for url, thumb in items:
                results.append({"url": url.replace("\\/", "/"), "thumbnail": thumb.replace("\\/", "/")})
        except:
            pass

    # Fallback to HTML parsing if JSON extraction is sparse
    if len(results) < 5:
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and "yandex" not in href.lower():
                # Look for an image child
                img = a.find('img', src=True)
                thumb = img['src'] if img else None
                if not any(x in href.lower() for x in ['.png', '.jpg', '.jpeg', '.svg', 'yastatic', 'captcha']):
                    results.append({"url": href, "thumbnail": thumb})

    # Filter and deduplicate
    filtered = []
    seen_urls = set()
    for res in results:
        url = res["url"]
        if url not in seen_urls and not any(x in url.lower() for x in ['pixel', 'favicon', 'ads']):
            seen_urls.add(url)
            filtered.append(res)

    return filtered

def extract_google_results(html):
    """Extracts both links and thumbnails from Google Lens results."""
    results = []
    # Google Lens often embeds results in a complex JS/HTML structure
    # We'll look for pattern of [link, thumbnail_url]

    # Try to find common patterns in the HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Google Lens result items often have specific data attributes or classes
    for div in soup.find_all(['div', 'a'], href=True):
        url = div['href']
        if url.startswith('http') and "google" not in url.lower():
            img = div.find('img', src=True)
            thumb = img['src'] if img else None
            results.append({"url": url, "thumbnail": thumb})

    # Regex fallback for embedded data
    links = re.findall(r'"(https?://[^"]+)"', html)
    for i in range(len(links) - 1):
        if is_social_profile(links[i]) and "gstatic" in links[i+1]:
            results.append({"url": links[i], "thumbnail": links[i+1]})

    filtered = []
    seen_urls = set()
    for res in results:
        url = res["url"]
        if url not in seen_urls and not any(x in url.lower() for x in ['gstatic', 'doubleclick', 'favicon', 'ads']):
            seen_urls.add(url)
            filtered.append(res)

    return filtered

def get_platform_name(url):
    if not url or not isinstance(url, str) or not url.startswith('http'):
        return "Website"
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        name = domain.split('.')[0].capitalize()

        social_map = {
            "instagram": "Instagram",
            "facebook": "Facebook",
            "tiktok": "TikTok",
            "twitter": "X",
            "x.com": "X",
            "linkedin": "LinkedIn",
            "pinterest": "Pinterest",
            "youtube": "YouTube",
            "snapchat": "Snapchat",
            "telegram": "Telegram",
            "reddit": "Reddit",
            "vk": "VK",
            "ok.ru": "OK.ru"
        }

        for k, v in social_map.items():
            if k in domain:
                return v
        return name
    except:
        return "Website"

async def facecheck_web_search(img_data: bytes):
    try:
        print("FaceCheck: Starting search process...")
        await asyncio.to_thread(scraper.get, "https://facecheck.id/", timeout=15)

        upload_url = "https://facecheck.id/api/upload_pic"
        files = {'images': ('image.jpg', img_data, 'image/jpeg')}
        headers = {
            "Referer": "https://facecheck.id/",
            "Origin": "https://facecheck.id",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest"
        }

        resp = await asyncio.to_thread(scraper.post, upload_url, files=files, headers=headers, timeout=25)
        if resp.status_code != 200:
            return []

        data = resp.json()
        id_search = data.get("id_search")
        if not id_search:
            return []

        search_url = "https://facecheck.id/api/search"
        payload = {"id_search": id_search, "with_progress": True, "status_only": False, "demo": False}

        for i in range(15):
            try:
                search_resp = await asyncio.to_thread(scraper.post, search_url, json=payload, headers=headers, timeout=20)
                if search_resp.status_code != 200: break

                search_data = search_resp.json()
                if search_data.get("progress", 0) >= 100:
                    items = search_data.get("output", {}).get("items", [])
                    results = []
                    for item in items:
                        url = item.get("url")
                        results.append({
                            "platform": get_platform_name(url) if url else "FaceCheck Match",
                            "url": url or "https://facecheck.id",
                            "score": item.get("score", 0),
                            "thumbnail": item.get("base64"),
                            "source": "facecheck"
                        })
                    return results
            except: pass
            await asyncio.sleep(2)
        return []
    except Exception as e:
        print(f"FaceCheck Error: {e}")
        return []

@app.get("/")
def home():
    return {"status": "Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    print("Search: Received new request.")
    try:
        img_data = await file.read()

        yandex_url = 'https://yandex.com/images/search'
        yandex_files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        yandex_params = {'rpt': 'imageview'}

        google_url = 'https://lens.google.com/upload'
        google_files = {'encoded_image': ('image.jpg', img_data, 'image/jpeg')}

        y_resp, g_resp, fc_results = await asyncio.gather(
            asyncio.to_thread(scraper.post, yandex_url, params=yandex_params, files=yandex_files, timeout=30),
            asyncio.to_thread(scraper.post, google_url, files=google_files, timeout=30),
            facecheck_web_search(img_data),
            return_exceptions=True
        )

        y_results = extract_yandex_results(y_resp.text) if not isinstance(y_resp, Exception) and y_resp.status_code == 200 else []
        g_results = extract_google_results(g_resp.text) if not isinstance(g_resp, Exception) and g_resp.status_code == 200 else []
        fc_results = fc_results if not isinstance(fc_results, Exception) else []

        # Combine all
        combined = []
        for r in fc_results: combined.append(r)

        for r in y_results + g_results:
            r["source"] = "web"
            r["platform"] = get_platform_name(r["url"])
            combined.append(r)

        # Ranking and Filtering
        def get_priority(item):
            source = item.get("source", "web")
            url = item.get("url", "")
            is_social = is_social_profile(url)
            if source == "facecheck": return 0 if is_social else 1
            return 2 if is_social else 3

        seen_urls = set()
        final_matches = []
        for item in combined:
            url = item.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                final_matches.append(item)

        final_matches.sort(key=get_priority)

        # Remove placeholder if better links exist
        if any("facecheck.id" not in m["url"].lower() for m in final_matches if m["url"]):
            final_matches = [m for m in final_matches if "facecheck.id" not in m["url"].lower()]

        return {
            "status": "success",
            "matches": final_matches[:100]
        }

    except Exception as e:
        print(f"Global Search Error: {e}")
        return {"status": "error", "message": str(e), "matches": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
