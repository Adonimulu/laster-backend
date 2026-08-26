from fastapi import FastAPI, File, UploadFile, Query
import cloudscraper
from bs4 import BeautifulSoup
import uvicorn
import os
from urllib.parse import urlparse

app = FastAPI()

# Stealth scraper to bypass bot detection
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome','platform': 'windows','mobile': False}
)

@app.get("/")
def home():
    return {"status": "Laster Biometric API is Online"}

@app.post("/search")
async def search(file: UploadFile = File(...), target_platform: str = Query(None)):
    try:
        # 1. Read the image data
        img_data = await file.read()

        # 2. Upload to Yandex Biometric Search
        # Yandex is world-class for finding specific people across the entire web
        search_url = 'https://yandex.com/images/search'
        files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        params = {'rpt': 'imageview', 'format': 'json'}

        response = scraper.post(search_url, params=params, files=files)
        soup = BeautifulSoup(response.text, 'html.parser')

        # 3. Extract all relevant external links (Finding presence "anywhere")
        links = []
        seen_urls = set()

        # System domains to exclude
        exclude = [
            'yandex.', 'google.', 'bing.', 'w3.org', 'schema.org',
            'javascript:', '#', 'market.yandex', 'alice.yandex',
            'yastatic.net', 'apple.com', 'microsoft.com'
        ]

        for a in soup.find_all('a', href=True):
            url = a['href']

            # Basic link validation
            if not url.startswith('http'): continue
            if any(x in url.lower() for x in exclude): continue
            if url in seen_urls: continue

            # Parse domain for identification
            parsed = urlparse(url)
            domain_full = parsed.netloc.lower()
            domain_simple = domain_full.replace('www.', '').split('.')[0].capitalize()

            # Identify platform
            platform = domain_simple
            if "instagram" in domain_full: platform = "Instagram"
            elif "facebook" in domain_full: platform = "Facebook"
            elif "tiktok" in domain_full: platform = "TikTok"
            elif "twitter" in domain_full or "x.com" in domain_full: platform = "X"
            elif "t.me" in domain_full: platform = "Telegram"
            elif "linkedin" in domain_full: platform = "LinkedIn"
            elif "youtube" in domain_full: platform = "YouTube"
            elif "pinterest" in domain_full: platform = "Pinterest"
            elif "reddit" in domain_full: platform = "Reddit"

            # Optional filtering if requested by app
            if target_platform and target_platform.lower() not in platform.lower() and target_platform.lower() not in url.lower():
                continue

            links.append({"platform": platform, "url": url})
            seen_urls.add(url)

        # Return top 15 matches for broader "anywhere" coverage
        return {"status": "success", "matches": links[:15]}

    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
