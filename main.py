import asyncio
import re
import os
import httpx # Using httpx (async) instead of requests for better performance
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright
from contextlib import asynccontextmanager

# Define directories
SAVE_DIR = "profile_photos"
os.makedirs(SAVE_DIR, exist_ok=True)

# 1. Lifespan Manager: Clean startup and shutdown of Playwright
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.playwright_instance = await async_playwright().start()
    # Launch with extreme memory-saving flags
    app.state.browser = await app.state.playwright_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--single-process",  # Crucial for 512MB RAM
            "--disable-gpu",
            "--no-zygote"
        ],
    )
    print("✅ Chromium browser launched via Lifespan")
    yield
    # Shutdown
    await app.state.browser.close()
    await app.state.playwright_instance.stop()
    print("🛑 Browser shutdown complete")

app = FastAPI(
    title="Instagram Profile Photo Downloader",
    description="Fetch profile photo using headless Chromium on Render",
    version="5.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def scrape_instagram_profile(username: str, browser) -> dict:
    """Open Instagram profile and extract data."""
    # Context with specific Mobile User Agent to trigger meta tags
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15",
        viewport={"width": 390, "height": 844},
    )
    # Inject App ID header to help bypass login walls
    await context.set_extra_http_headers({"X-IG-App-ID": "936619743392459"})
    
    page = await context.new_page()

    try:
        url = f"https://www.instagram.com/{username}/"
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        if response and response.status == 404:
            raise HTTPException(status_code=404, detail=f"Profile '@{username}' not found")

        await page.wait_for_timeout(3000)

        # Extraction logic (same as your original)
        profile_pic_url = await page.evaluate("() => document.querySelector('meta[property=\"og:image\"]')?.content || ''")
        og_description = await page.evaluate("() => document.querySelector('meta[property=\"og:description\"]')?.content || ''")

        if not profile_pic_url:
             raise Exception("Instagram triggered a login wall. No meta data found.")

        # Parse counts (Followers, Following, Posts)
        followers = 0
        f_match = re.search(r"([\d,.]+[KMB]?)\s*Followers", og_description, re.IGNORECASE)
        if f_match:
            followers = parse_count(f_match.group(1))

        return {
            "username": username,
            "followers": followers,
            "profile_pic_url": profile_pic_url,
        }
    finally:
        await context.close()

def parse_count(value: str) -> int:
    value = value.strip().replace(",", "")
    multiplier = 1
    if value.upper().endswith("K"): multiplier = 1_000; value = value[:-1]
    elif value.upper().endswith("M"): multiplier = 1_000_000; value = value[:-1]
    try:
        return int(float(value) * multiplier)
    except:
        return 0

async def download_image(url: str, username: str) -> str | None:
    """Async download using httpx."""
    dest_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=15.0)
            if resp.status_code == 200:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
                return dest_path
        except Exception as e:
            print(f"⚠️ Download error: {e}")
    return None

@app.get("/profile/{username}")
async def get_profile(username: str):
    username = username.strip().lstrip("@").lower()
    try:
        # Pass the browser instance from app state
        data = await scrape_instagram_profile(username, app.state.browser)
        saved_path = await download_image(data["profile_pic_url"], username)
        
        return {
            "success": True,
            **data,
            "download_url": f"/download/{username}" if saved_path else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{username}")
async def download_photo(username: str):
    file_path = os.path.join(SAVE_DIR, f"{username.lower()}_profile_pic.jpg")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(file_path)

@app.get("/health")
def health():
    return {"status": "ok"}