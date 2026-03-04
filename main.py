"""
Instagram Profile Photo Downloader - FastAPI + Playwright
==========================================================
Uses a real headless Chromium browser to fetch Instagram profiles.
Same approach as the Swiggy restaurant scraper.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright
import asyncio
import re
import os
import requests

app = FastAPI(
    title="Instagram Profile Photo Downloader",
    description="Fetch profile photo & stats using headless Chromium",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SAVE_DIR = "profile_photos"
os.makedirs(SAVE_DIR, exist_ok=True)

# Global browser instance (reused across requests)
browser = None
playwright_instance = None


async def get_browser():
    """Launch or reuse a persistent Chromium browser."""
    global browser, playwright_instance

    if browser and browser.is_connected():
        return browser

    playwright_instance = await async_playwright().start()
    browser = await playwright_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ],
    )
    return browser


async def scrape_instagram_profile(username: str) -> dict:
    """Open Instagram profile in headless Chromium and extract data."""

    br = await get_browser()
    context = await br.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        viewport={"width": 390, "height": 844},
        locale="en-US",
    )

    page = await context.new_page()

    try:
        # Block unnecessary resources to speed up loading
        await page.route("**/*.{mp4,webm,ogg,mp3,wav}", lambda route: route.abort())
        await page.route("**/logging_client_events*", lambda route: route.abort())
        await page.route("**/batch/log*", lambda route: route.abort())

        url = f"https://www.instagram.com/{username}/"
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        if response and response.status == 404:
            raise HTTPException(status_code=404, detail=f"Profile '@{username}' not found")

        # Wait a bit for page to settle
        await page.wait_for_timeout(3000)

        # --- Extract from meta tags (most reliable) ---
        profile_pic_url = await page.evaluate("""
            () => {
                const meta = document.querySelector('meta[property="og:image"]');
                return meta ? meta.content : '';
            }
        """)

        og_title = await page.evaluate("""
            () => {
                const meta = document.querySelector('meta[property="og:title"]');
                return meta ? meta.content : '';
            }
        """)

        og_description = await page.evaluate("""
            () => {
                const meta = document.querySelector('meta[property="og:description"]');
                return meta ? meta.content : '';
            }
        """)

        meta_description = await page.evaluate("""
            () => {
                const meta = document.querySelector('meta[name="description"]');
                return meta ? meta.content : '';
            }
        """)

        # --- If meta tags are empty (login wall), try intercepting API calls ---
        if not profile_pic_url:
            profile_pic_url = await try_api_intercept(page, username)

        # --- Parse extracted data ---
        full_name = ""
        if og_title:
            name_match = re.match(r"^(.*?)\s*\(@", og_title)
            if name_match:
                full_name = name_match.group(1).strip()

        desc = og_description or meta_description or ""
        followers, following, posts_count = 0, 0, 0

        f_match = re.search(r"([\d,.]+[KMB]?)\s*Followers", desc, re.IGNORECASE)
        fw_match = re.search(r"([\d,.]+[KMB]?)\s*Following", desc, re.IGNORECASE)
        p_match = re.search(r"([\d,.]+[KMB]?)\s*Posts", desc, re.IGNORECASE)

        if f_match:
            followers = parse_count(f_match.group(1))
        if fw_match:
            following = parse_count(fw_match.group(1))
        if p_match:
            posts_count = parse_count(p_match.group(1))

        # Bio
        bio = ""
        bio_text = meta_description or desc
        bio_clean = re.sub(r"See Instagram photos and videos.*$", "", bio_text).strip()
        bio_clean = re.sub(r"^[\d,.]+[KMB]?\s*Followers.*?Posts\s*[-–—]\s*", "", bio_clean).strip()
        if bio_clean and bio_clean != desc:
            bio = bio_clean

        # Private / Verified from page content
        page_content = await page.content()
        is_private = '"is_private":true' in page_content
        is_verified = '"is_verified":true' in page_content

        if not profile_pic_url:
            raise Exception(
                "Could not extract profile picture. Instagram may be showing a login wall."
            )

        return {
            "username": username,
            "full_name": full_name,
            "bio": bio,
            "followers": followers,
            "following": following,
            "posts": posts_count,
            "is_private": is_private,
            "is_verified": is_verified,
            "profile_pic_url": profile_pic_url,
        }

    finally:
        await context.close()


async def try_api_intercept(page, username: str) -> str:
    """
    If meta tags are empty, try navigating as mobile and
    intercept the profile API response for profile pic URL.
    """
    profile_pic_url = ""

    async def handle_response(response):
        nonlocal profile_pic_url
        url = response.url
        if "web_profile_info" in url or "graphql" in url:
            try:
                data = await response.json()
                user = (
                    data.get("data", {}).get("user", {})
                    or data.get("graphql", {}).get("user", {})
                    or {}
                )
                if user:
                    profile_pic_url = (
                        user.get("profile_pic_url_hd", "")
                        or user.get("profile_pic_url", "")
                    )
            except Exception:
                pass

    page.on("response", handle_response)

    try:
        await page.goto(
            f"https://www.instagram.com/{username}/",
            wait_until="networkidle",
            timeout=15000,
        )
        await page.wait_for_timeout(3000)
    except Exception:
        pass

    return profile_pic_url


def parse_count(value: str) -> int:
    """Parse count strings like '1.2M', '500K', '1,234'."""
    value = value.strip().replace(",", "")
    multiplier = 1
    if value.upper().endswith("K"):
        multiplier = 1_000
        value = value[:-1]
    elif value.upper().endswith("M"):
        multiplier = 1_000_000
        value = value[:-1]
    elif value.upper().endswith("B"):
        multiplier = 1_000_000_000
        value = value[:-1]
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return 0


def download_image(url: str, username: str) -> str | None:
    """Download profile image from Instagram's CDN."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)"
        })
        if resp.status_code == 200:
            dest_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return dest_path
    except Exception as e:
        print(f"⚠️ Image download failed: {e}")
    return None


# ============================================================
# Startup / Shutdown
# ============================================================

@app.on_event("startup")
async def startup():
    """Pre-launch the browser on startup for faster first request."""
    await get_browser()
    print("✅ Chromium browser launched and ready")


@app.on_event("shutdown")
async def shutdown():
    global browser, playwright_instance
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()


# ============================================================
# Routes
# ============================================================

@app.get("/")
def root():
    return {
        "message": "Instagram Profile Photo Downloader API v5",
        "powered_by": "Playwright + Headless Chromium",
        "usage": "GET /profile/{username}",
        "docs": "Visit /docs for Swagger UI",
    }


@app.get("/profile/{username}")
async def get_profile(username: str):
    """Fetch profile stats and download the profile photo."""

    username = username.strip().lstrip("@").lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")

    try:
        data = await scrape_instagram_profile(username)

        # Download the profile pic from CDN
        saved_path = download_image(data.get("profile_pic_url", ""), username)

        return {
            "success": True,
            **data,
            "download_url": f"/download/{username}" if saved_path else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{username}")
def download_photo(username: str):
    """Download the saved profile photo as a file."""

    username = username.strip().lstrip("@").lower()
    file_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Photo not found. Fetch it first via GET /profile/{username}",
        )

    return FileResponse(
        path=file_path,
        filename=f"{username}_profile_pic.jpg",
        media_type="image/jpeg",
    )


@app.get("/health")
def health_check():
    connected = browser.is_connected() if browser else False
    return {
        "status": "healthy",
        "version": "5.0.0",
        "browser_connected": connected,
    }
