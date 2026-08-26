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

# Enhanced scraper setup
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome','platform': 'windows','mobile': False}
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

@app.get("/")
def home():
    return {"status": "Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    try:
        img_data = await file.read()

        # We'll use Yandex for the primary "biometric" heavy lifting
        # and Google Lens for "context" results.

        yandex_url = 'https://yandex.com/images/search'
        yandex_files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        yandex_params = {'rpt': 'imageview'}

        google_url = 'https://lens.google.com/upload'
        google_files = {'encoded_image': ('image.jpg', img_data, 'image/jpeg')}

        # Parallel Execution
        y_resp, g_resp = await asyncio.gather(
            asyncio.to_thread(scraper.post, yandex_url, params=yandex_params, files=yandex_files, timeout=20),
            asyncio.to_thread(scraper.post, google_url, files=google_files, timeout=20)
        )

        y_links = extract_yandex_links(y_resp.text)
        g_links = extract_google_links(g_resp.text)

        all_links = y_links + [l for l in g_links if l not in y_links]

        matches = []
        for l in all_links[:60]:
            matches.append({
                "platform": get_platform_name(l),
                "url": l
            })

        return {
            "status": "success",
            "matches": matches,
            "engines": {
                "yandex": y_resp.url if y_resp.status_code == 200 else None,
                "google": g_resp.url if g_resp.status_code == 200 else None
            }
        }

    except Exception as e:
        print(f"Error: {e}")
        return {"status": "success", "matches": []}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
