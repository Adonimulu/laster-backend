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

def extract_yandex_links(html):
    links = []
    soup = BeautifulSoup(html, 'html.parser')

    # 1. Best matches (Sites where image is found)
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('http') and "yandex" not in href.lower():
            # Filter out generic assets
            if not any(x in href.lower() for x in ['.png', '.jpg', '.jpeg', '.svg', 'yastatic', 'captcha']):
                links.append(href)

    # 2. Extract from JSON state if present
    match = re.search(r'data-state="({.*?})"', html)
    if match:
        try:
            data = json.loads(match.group(1).replace('&quot;', '"'))
            urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', str(data))
            links.extend([u for u in urls if "yandex" not in u.lower()])
        except:
            pass

    return list(dict.fromkeys(links)) # Unique links

def extract_google_links(html):
    # Google Lens results in HTML
    links = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+/(?:[-\w./?%&=]*)?', html)
    filtered = []
    for l in links:
        if "google" not in l.lower() and l.startswith('http'):
            if not any(x in l.lower() for x in ['.png', '.jpg', '.jpeg', 'gstatic', 'doubleclick']):
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
        # Step 0: Initial GET to establish session and cookies
        await asyncio.to_thread(scraper.get, "https://facecheck.id/", timeout=10)

        # Step 1: Upload the image to the internal API
        upload_url = "https://facecheck.id/api/upload_pic"
        files = {'images': ('image.jpg', img_data, 'image/jpeg')}
        headers = {
            "Referer": "https://facecheck.id/",
            "Origin": "https://facecheck.id",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest"
        }

        resp = await asyncio.to_thread(scraper.post, upload_url, files=files, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"FaceCheck Upload Failed: {resp.status_code}")
            return []

        data = resp.json()
        id_search = data.get("id_search")
        if not id_search:
            print("FaceCheck Upload failed to return id_search")
            return []

        # Step 2: Initiate search and poll for progress
        search_url = "https://facecheck.id/api/search"
        payload = {
            "id_search": id_search,
            "with_progress": True,
            "status_only": False,
            "demo": False # Set to True if hitting rate limits on free search
        }

        # Polling loop (max ~30-40 seconds)
        for _ in range(20):
            search_resp = await asyncio.to_thread(scraper.post, search_url, json=payload, headers=headers, timeout=20)
            if search_resp.status_code != 200:
                print(f"FaceCheck Search Polling Error: {search_resp.status_code}")
                break

            search_data = search_resp.json()
            progress = search_data.get("progress", 0)

            if progress >= 100:
                output = search_data.get("output", {})
                items = output.get("items", [])

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

            # Wait 2 seconds before next poll
            await asyncio.sleep(2)

        return []
    except Exception as e:
        print(f"FaceCheck Scraper Error: {e}")
        return []

@app.get("/")
def home():
    return {"status": "Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    try:
        img_data = await file.read()

        # Engine endpoints
        yandex_url = 'https://yandex.com/images/search'
        yandex_files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        yandex_params = {'rpt': 'imageview'}

        google_url = 'https://lens.google.com/upload'
        google_files = {'encoded_image': ('image.jpg', img_data, 'image/jpeg')}

        # Parallel Execution of all search engines
        y_resp, g_resp, fc_results = await asyncio.gather(
            asyncio.to_thread(scraper.post, yandex_url, params=yandex_params, files=yandex_files, timeout=25),
            asyncio.to_thread(scraper.post, google_url, files=google_files, timeout=25),
            facecheck_web_search(img_data)
        )

        # Extract links from traditional engines
        y_links = extract_yandex_links(y_resp.text) if y_resp.status_code == 200 else []
        g_links = extract_google_links(g_resp.text) if g_resp.status_code == 200 else []

        # Consolidate results
        matches = []

        # 1. Prioritize FaceCheck Results (High quality biometric matches)
        for res in fc_results:
            matches.append(res)

        # 2. Add Yandex and Google results, avoiding duplicates from FaceCheck
        existing_urls = {m.get("url") for m in matches if m.get("url") and m.get("url") != "https://facecheck.id"}
        all_web_links = y_links + [l for l in g_links if l not in y_links]

        for l in all_web_links:
            if l not in existing_urls:
                matches.append({
                    "platform": get_platform_name(l),
                    "url": l
                })

        return {
            "status": "success",
            "matches": matches[:100],
            "engines": {
                "yandex": y_resp.url if y_resp.status_code == 200 else None,
                "google": g_resp.url if g_resp.status_code == 200 else None,
                "facecheck": "https://facecheck.id"
            }
        }

    except Exception as e:
        print(f"Global Search Error: {e}")
        return {"status": "error", "message": str(e), "matches": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
