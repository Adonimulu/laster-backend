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

def extract_yandex_links(html):
    links = []
    # Aggressive URL extraction from text
    urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', html)
    links.extend(urls)

    soup = BeautifulSoup(html, 'html.parser')
    # 1. Best matches (Sites where image is found)
    for a in soup.find_all('a', href=True):
        links.append(a['href'])

    # 2. Extract from JSON state if present
    match = re.search(r'data-state="({.*?})"', html)
    if match:
        try:
            data = json.loads(match.group(1).replace('&quot;', '"'))
            json_urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', str(data))
            links.extend(json_urls)
        except:
            pass

    filtered = []
    for l in links:
        l_lower = l.lower()
        if l.startswith('http') and "yandex" not in l_lower:
            # Filter out generic assets and noise
            if not any(x in l_lower for x in ['.png', '.jpg', '.jpeg', '.svg', 'yastatic', 'captcha', 'pixel', 'favicon', 'ads']):
                filtered.append(l)

    return list(dict.fromkeys(filtered))

def extract_google_links(html):
    # Aggressive URL extraction
    links = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', html)

    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        links.append(a['href'])

    filtered = []
    for l in links:
        l_lower = l.lower()
        if l.startswith('http') and "google" not in l_lower:
            if not any(x in l_lower for x in ['.png', '.jpg', '.jpeg', 'gstatic', 'doubleclick', 'favicon', 'ads']):
                filtered.append(l)
    return list(dict.fromkeys(filtered))

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
    """
    Performs a facial recognition search on FaceCheck.id by mimicking the web UI flow.
    Uses cloudscraper to bypass Cloudflare protection.
    """
    try:
        print("FaceCheck: Starting search process...")
        # Step 0: Initial GET to establish session and cookies
        await asyncio.to_thread(scraper.get, "https://facecheck.id/", timeout=15)
        print("FaceCheck: Session established.")

        # Step 1: Upload the image to the internal API
        upload_url = "https://facecheck.id/api/upload_pic"
        files = {'images': ('image.jpg', img_data, 'image/jpeg')}
        headers = {
            "Referer": "https://facecheck.id/",
            "Origin": "https://facecheck.id",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest"
        }

        print("FaceCheck: Uploading image...")
        resp = await asyncio.to_thread(scraper.post, upload_url, files=files, headers=headers, timeout=25)
        if resp.status_code != 200:
            print(f"FaceCheck: Upload Failed with status {resp.status_code}")
            return []

        data = resp.json()
        id_search = data.get("id_search")
        if not id_search:
            print("FaceCheck: No id_search returned in response.")
            return []

        print(f"FaceCheck: Upload successful. Search ID: {id_search}")

        # Step 2: Initiate search and poll for progress
        search_url = "https://facecheck.id/api/search"
        payload = {
            "id_search": id_search,
            "with_progress": True,
            "status_only": False,
            "demo": False
        }

        # Reduced polling loop to 15 iterations (30s total) for client resilience
        print("FaceCheck: Starting polling...")
        for i in range(15):
            try:
                search_resp = await asyncio.to_thread(scraper.post, search_url, json=payload, headers=headers, timeout=20)
                if search_resp.status_code != 200:
                    print(f"FaceCheck: Polling error on iteration {i}, status: {search_resp.status_code}")
                    break

                search_data = search_resp.json()
                progress = search_data.get("progress", 0)
                print(f"FaceCheck: Progress {progress}%")

                if progress >= 100:
                    output = search_data.get("output", {})
                    items = output.get("items", [])
                    print(f"FaceCheck: Search complete. Found {len(items)} items.")

                    results = []
                    for item in items:
                        url = item.get("url")
                        results.append({
                            "platform": get_platform_name(url) if url else "FaceCheck Match",
                            "url": url or "https://facecheck.id",
                            "score": item.get("score", 0),
                            "thumbnail": item.get("base64")
                        })
                    return results
            except Exception as poll_e:
                print(f"FaceCheck: Exception during poll {i}: {poll_e}")

            # Wait 2 seconds before next poll
            await asyncio.sleep(2)

        print("FaceCheck: Polling timed out after 15 iterations.")
        return []
    except Exception as e:
        print(f"FaceCheck: Global Scraper Error: {e}")
        return []

@app.get("/")
def home():
    print("Health check requested.")
    return {"status": "Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    print("Search: Received new request.")
    try:
        img_data = await file.read()
        print(f"Search: Read {len(img_data)} bytes of image data.")

        # Engine endpoints
        yandex_url = 'https://yandex.com/images/search'
        yandex_files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        yandex_params = {'rpt': 'imageview'}

        google_url = 'https://lens.google.com/upload'
        google_files = {'encoded_image': ('image.jpg', img_data, 'image/jpeg')}

        print("Search: Triggering parallel engines...")
        # Parallel Execution
        y_resp, g_resp, fc_results = await asyncio.gather(
            asyncio.to_thread(scraper.post, yandex_url, params=yandex_params, files=yandex_files, timeout=30),
            asyncio.to_thread(scraper.post, google_url, files=google_files, timeout=30),
            facecheck_web_search(img_data),
            return_exceptions=True
        )

        # Handle exceptions from gather - resilience: errors don't stop other engines
        y_links = []
        if not isinstance(y_resp, Exception) and y_resp.status_code == 200:
            y_links = extract_yandex_links(y_resp.text)
        elif isinstance(y_resp, Exception):
            print(f"Search: Yandex error: {y_resp}")

        g_links = []
        if not isinstance(g_resp, Exception) and g_resp.status_code == 200:
            g_links = extract_google_links(g_resp.text)
        elif isinstance(g_resp, Exception):
            print(f"Search: Google Lens error: {g_resp}")

        if isinstance(fc_results, Exception):
            print(f"Search: FaceCheck error: {fc_results}")
            fc_results = []

        print(f"Search: Engine counts -> Yandex: {len(y_links)}, Google: {len(g_links)}, FaceCheck: {len(fc_results)}")

        # Consolidate and Rank results
        raw_results = []

        # 1. Collect FaceCheck results
        for res in fc_results:
            res["source"] = "facecheck"
            raw_results.append(res)

        # 2. Collect web links
        combined_web = list(dict.fromkeys(y_links + g_links))
        for l in combined_web:
            raw_results.append({
                "platform": get_platform_name(l),
                "url": l,
                "source": "web"
            })

        # Helper to define sorting priority
        def get_priority(item):
            source = item.get("source", "web")
            url = item.get("url", "")
            is_social = is_social_profile(url)

            if source == "facecheck":
                if is_social: return 0  # Biometric + Social (Highest)
                return 1               # Biometric Generic
            if is_social: return 2     # Web Social
            return 3                   # Web Generic (Lowest)

        # Filter duplicates and placeholders
        seen_urls = set()
        unique_results = []
        for item in raw_results:
            url = item.get("url")
            if url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique_results.append(item)

        # Sort based on priority
        unique_results.sort(key=get_priority)

        # Clean: Filter out "facecheck.id" placeholder if better links are found
        has_real_links = any(m.get("url") and "facecheck.id" not in m.get("url").lower() for m in unique_results)
        if has_real_links:
            unique_results = [m for m in unique_results if "facecheck.id" not in m.get("url").lower()]

        print(f"Search: Returning {len(unique_results)} total matches.")
        return {
            "status": "success",
            "matches": unique_results[:100],
            "engines": {
                "yandex": y_resp.url if hasattr(y_resp, 'url') and y_resp.status_code == 200 else None,
                "google": g_resp.url if hasattr(g_resp, 'url') and g_resp.status_code == 200 else None,
                "facecheck": "https://facecheck.id"
            }
        }

    except Exception as e:
        print(f"Global Search Error: {e}")
        return {"status": "error", "message": str(e), "matches": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
