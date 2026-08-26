from fastapi import FastAPI, File, UploadFile
import cloudscraper
from bs4 import BeautifulSoup
import uvicorn
import os
import re
import json
from urllib.parse import urlparse

app = FastAPI()

# Stealth scraper with custom headers to maximize success rate
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome','platform': 'windows','mobile': False}
)

@app.get("/")
def home():
    return {"status": "Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    try:
        img_data = await file.read()
        
        # 1. Target the world's most aggressive face-index engine
        search_url = 'https://yandex.com/images/search'
        files = {'upfile': ('image.jpg', img_data, 'image/jpeg')}
        params = {'rpt': 'imageview'} # Removed 'format:json' to get the full results page
        
        response = scraper.post(search_url, params=params, files=files)
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        links = []
        seen_urls = set()

        # 2. Strategy A: Extract from "Sites where image is found" (Specific matches)
        # Yandex often stores these in a JSON blob called 'data-state'
        data_state = soup.find('div', {'class': 'cbir-section_name_sites'})
        if data_state:
            for a in data_state.find_all('a', href=True):
                url = a['href']
                if url.startswith('http') and url not in seen_urls:
                    links.append(url)
                    seen_urls.add(url)

        # 3. Strategy B: Global Link Scraping (Broad presence)
        # Catch anything that wasn't in the specific 'sites' section
        for a in soup.find_all('a', href=True):
            url = a['href']
            if not url.startswith('http'): continue
            if any(x in url.lower() for x in ['yandex', 'yastatic', 'captcha', 'feedback', 'market']): continue
            if url in seen_urls: continue
            links.append(url)
            seen_urls.add(url)

        # 4. Format the final output for the Android App
        matches = []
        for url in links:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace('www.', '')
            platform = domain.split('.')[0].capitalize()
            
            # Map specific popular platforms for better icons in the app
            if "instagram" in domain: platform = "Instagram"
            elif "facebook" in domain: platform = "Facebook"
            elif "tiktok" in domain: platform = "TikTok"
            elif "twitter" in domain or "x.com" in domain: platform = "X"
            elif "linkedin" in domain: platform = "LinkedIn"
            elif "pinterest" in domain: platform = "Pinterest"
            elif "youtube" in domain: platform = "YouTube"
            
            matches.append({"platform": platform, "url": url})

        # Return the top 20 matches. If none, return empty success (silent).
        return {"status": "success", "matches": matches[:20]}
        
    except Exception as e:
        print(f"Internal Error: {e}")
        return {"status": "success", "matches": []}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
