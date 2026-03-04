"""
Instagram Profile Photo Downloader - FastAPI Backend v2
========================================================
Uses requests + BeautifulSoup instead of instaloader.
Mimics a real browser to avoid Instagram's bot detection.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import requests
import re
import json
import os
import shutil
from bs4 import BeautifulSoup
from urllib.parse import urlparse

app = FastAPI(
    title="Instagram Profile Photo Downloader",
    description="Fetch profile photo & stats of any public Instagram account",
    version="2.0.0",
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

# --- Browser-like headers to avoid bot detection ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# Persistent session to maintain cookies across requests
session = requests.Session()
session.headers.update(HEADERS)


def extract_profile_data(username: str) -> dict:
    """
    Fetch Instagram profile page and extract data from:
    1. og:image meta tag (profile pic)
    2. Embedded JSON in <script> tags (stats)
    """

    url = f"https://www.instagram.com/{username}/"

    # First hit the homepage to get cookies (csrftoken, mid, ig_did etc.)
    try:
        session.get("https://www.instagram.com/", timeout=10)
    except Exception:
        pass

    response = session.get(url, timeout=15)

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Profile '@{username}' does not exist")

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Instagram returned status {response.status_code}",
        )

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    # --- Extract profile pic from og:image ---
    profile_pic_url = None
    og_image = soup.find("meta", property="og:image")
    if og_image:
        profile_pic_url = og_image.get("content")

    # --- Extract description (has follower counts) from og:description ---
    description = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        description = og_desc.get("content", "")

    # --- Try to extract full name from title ---
    full_name = ""
    title_tag = soup.find("meta", property="og:title")
    if title_tag:
        title_text = title_tag.get("content", "")
        # Format: "Full Name (@username) • Instagram photos and videos"
        match = re.match(r"^(.*?)\s*\(@", title_text)
        if match:
            full_name = match.group(1).strip()

    # --- Parse follower/following/posts from description ---
    # Format: "1.2M Followers, 500 Following, 300 Posts - See Instagram..."
    followers = 0
    following = 0
    posts = 0

    followers_match = re.search(r"([\d,.]+[KMB]?)\s*Followers", description, re.IGNORECASE)
    following_match = re.search(r"([\d,.]+[KMB]?)\s*Following", description, re.IGNORECASE)
    posts_match = re.search(r"([\d,.]+[KMB]?)\s*Posts", description, re.IGNORECASE)

    if followers_match:
        followers = parse_count(followers_match.group(1))
    if following_match:
        following = parse_count(following_match.group(1))
    if posts_match:
        posts = parse_count(posts_match.group(1))

    # --- Try to extract more data from embedded JSON ---
    bio = ""
    is_private = False
    is_verified = False

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                if "description" in data:
                    bio = data.get("description", "")
                if "name" in data and not full_name:
                    full_name = data.get("name", "")
        except (json.JSONDecodeError, TypeError):
            pass

    # Also search for SharedData or similar JSON blobs
    for script in soup.find_all("script"):
        if script.string and "is_private" in (script.string or ""):
            try:
                # Look for JSON objects with profile data
                json_match = re.search(r'\{[^{}]*"is_private"\s*:\s*(true|false)[^{}]*\}', script.string)
                if json_match:
                    is_private = json_match.group(1) == "true"
                verified_match = re.search(r'"is_verified"\s*:\s*(true|false)', script.string)
                if verified_match:
                    is_verified = verified_match.group(1) == "true"
            except Exception:
                pass

    if not profile_pic_url:
        raise HTTPException(
            status_code=500,
            detail="Could not extract profile picture. Instagram may have blocked this request.",
        )

    return {
        "username": username,
        "full_name": full_name,
        "bio": bio,
        "followers": followers,
        "following": following,
        "posts": posts,
        "is_private": is_private,
        "is_verified": is_verified,
        "profile_pic_url": profile_pic_url,
    }


def parse_count(value: str) -> int:
    """Parse Instagram count strings like '1.2M', '500K', '1,234'."""
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
    """Download the profile image from Instagram's CDN."""
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            dest_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return dest_path
    except Exception as e:
        print(f"Failed to download image: {e}")
    return None


# === ROUTES ===

@app.get("/")
def root():
    return {
        "message": "Instagram Profile Photo Downloader API v2",
        "usage": "GET /profile/{username}",
        "docs": "Visit /docs for Swagger UI",
    }


@app.get("/profile/{username}")
def get_profile(username: str):
    """Fetch profile stats and download the profile photo."""

    username = username.strip().lstrip("@").lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")

    try:
        data = extract_profile_data(username)

        # Download the profile pic to local storage
        saved_path = None
        if data["profile_pic_url"]:
            saved_path = download_image(data["profile_pic_url"], username)

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
    return {"status": "healthy", "version": "2.0.0"}
