from fastapi import FastAPI, File, UploadFile
import cloudscraper
from bs4 import BeautifulSoup
import uvicorn
import os

app = FastAPI()

# Stealth scraper to bypass bot detection
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome','platform': 'windows','mobile': False}
)

@app.get("/")
def home():
    return {"status": "Laster Biometric API is Online"}

@app.post("/search")
async def search(file: UploadFile = File(...)):
    try:
        # 1. Read the face image from the Android app
        img_data = await file.read()
        
        # 2. Proxy Search via Yandex (The world's most accurate face index)
        # We upload the image directly to Yandex's biometric engine
        search_url = 'https://yandex.com/images/search'
        files = {'upfile': ('face.jpg', img_data, 'image/jpeg')}
        params = {'rpt': 'imageview', 'format': 'json'}
        
        response = scraper.post(search_url, params=params, files=files)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 3. Extract Instagram, Facebook, and TikTok links
        links = []
        for a in soup.find_all('a', href=True):
            url = a['href']
            # We filter for the platforms you want
            if any(x in url for x in ['instagram.com', 'facebook.com', 'tiktok.com', 'twitter.com', 't.me']):
                platform = "Target Found"
                if "instagram" in url: platform = "Instagram"
                elif "facebook" in url: platform = "Facebook"
                elif "tiktok" in url: platform = "TikTok"
                
                links.append({"platform": platform, "url": url})
        
        # Return the top 10 most accurate matches
        return {"status": "success", "matches": links[:10]}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # Render uses port 10000 by default for free services
    uvicorn.run(app, host="0.0.0.0", port=10000)
