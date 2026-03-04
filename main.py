"""
Instagram Profile Photo Downloader - FastAPI Backend v3
========================================================
Performs actual Instagram web login to get session cookies,
then fetches profile data as an authenticated user.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import requests
import json
import os
import re
import time
import hashlib

app = FastAPI(
    title="Instagram Profile Photo Downloader",
    description="Fetch profile photo & stats of any public Instagram account",
    version="3.0.0",
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

# ============================================================
# Instagram Session Manager
# ============================================================

class InstagramSession:
    """Manages authenticated Instagram web session."""

    BASE_URL = "https://www.instagram.com"
    LOGIN_URL = "https://www.instagram.com/accounts/login/ajax/"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })
        self.logged_in = False
        self.login_username = None

    def login(self, username: str, password: str) -> bool:
        """Perform Instagram web login and store session cookies."""
        try:
            # Step 1: Visit Instagram homepage to get initial cookies (csrftoken, mid)
            print("🔑 Step 1: Fetching Instagram homepage for cookies...")
            resp = self.session.get(self.BASE_URL, timeout=15)
            time.sleep(1)

            # Get CSRF token from cookies
            csrf_token = self.session.cookies.get("csrftoken", "")
            if not csrf_token:
                # Try to extract from page source
                match = re.search(r'"csrf_token":"([^"]+)"', resp.text)
                if match:
                    csrf_token = match.group(1)

            if not csrf_token:
                print("❌ Could not get CSRF token")
                return False

            print(f"✅ Got CSRF token: {csrf_token[:10]}...")

            # Step 2: Send login request
            print("🔑 Step 2: Logging in...")
            timestamp = int(time.time())

            login_data = {
                "username": username,
                "enc_password": f"#PWD_INSTAGRAM_BROWSER:0:{timestamp}:{password}",
                "queryParams": "{}",
                "optIntoOneTap": "false",
                "trustedDeviceRecords": "{}",
            }

            login_headers = {
                "X-CSRFToken": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "X-Instagram-AJAX": "1",
                "Referer": "https://www.instagram.com/accounts/login/",
                "Origin": "https://www.instagram.com",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            resp = self.session.post(
                self.LOGIN_URL,
                data=login_data,
                headers=login_headers,
                timeout=15,
            )

            result = resp.json()
            print(f"📦 Login response: {json.dumps(result, indent=2)}")

            if result.get("authenticated"):
                self.logged_in = True
                self.login_username = username
                print(f"✅ Successfully logged in as @{username}")
                return True
            else:
                msg = result.get("message", "Unknown error")
                print(f"❌ Login failed: {msg}")
                # Check for checkpoint/challenge
                if result.get("checkpoint_url"):
                    print(f"⚠️ Account needs verification: {result['checkpoint_url']}")
                return False

        except Exception as e:
            print(f"❌ Login error: {e}")
            return False

    def get_profile_data(self, username: str) -> dict:
        """Fetch profile data using the authenticated session."""

        # Method 1: Try the web profile info API (works when logged in)
        try:
            return self._fetch_via_api(username)
        except Exception as e:
            print(f"⚠️ API method failed: {e}")

        # Method 2: Try the GraphQL endpoint
        try:
            return self._fetch_via_graphql(username)
        except Exception as e:
            print(f"⚠️ GraphQL method failed: {e}")

        # Method 3: Fallback to HTML parsing
        try:
            return self._fetch_via_html(username)
        except Exception as e:
            print(f"⚠️ HTML method failed: {e}")

        raise Exception("All methods failed to fetch profile data")

    def _fetch_via_api(self, username: str) -> dict:
        """Fetch via Instagram's web profile info API."""
        url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"

        headers = {
            "User-Agent": self.USER_AGENT,
            "X-IG-App-ID": "936619743392459",  # Instagram web app ID
            "X-IG-WWW-Claim": "0",
            "Origin": "https://www.instagram.com",
            "Referer": f"https://www.instagram.com/{username}/",
        }

        resp = self.session.get(url, headers=headers, timeout=15)

        if resp.status_code == 429:
            raise Exception("Rate limited on API endpoint")
        if resp.status_code != 200:
            raise Exception(f"API returned {resp.status_code}")

        data = resp.json()
        user = data.get("data", {}).get("user", {})

        if not user:
            raise Exception("No user data in API response")

        return {
            "username": username,
            "full_name": user.get("full_name", ""),
            "bio": user.get("biography", ""),
            "followers": user.get("edge_followed_by", {}).get("count", 0),
            "following": user.get("edge_follow", {}).get("count", 0),
            "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
            "is_private": user.get("is_private", False),
            "is_verified": user.get("is_verified", False),
            "profile_pic_url": user.get("profile_pic_url_hd", user.get("profile_pic_url", "")),
        }

    def _fetch_via_graphql(self, username: str) -> dict:
        """Fetch via Instagram's GraphQL endpoint."""
        url = "https://www.instagram.com/graphql/query/"

        variables = json.dumps({
            "username": username,
            "render_surface": "PROFILE",
        })

        params = {
            "doc_id": "7950326498356165",  # Public profile query doc_id
            "variables": variables,
        }

        headers = {
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/{username}/",
        }

        resp = self.session.get(url, params=params, headers=headers, timeout=15)

        if resp.status_code != 200:
            raise Exception(f"GraphQL returned {resp.status_code}")

        data = resp.json()
        user = data.get("data", {}).get("user", {})

        if not user:
            raise Exception("No user data in GraphQL response")

        return {
            "username": username,
            "full_name": user.get("full_name", ""),
            "bio": user.get("biography", ""),
            "followers": user.get("edge_followed_by", {}).get("count", 0) if "edge_followed_by" in user else user.get("follower_count", 0),
            "following": user.get("edge_follow", {}).get("count", 0) if "edge_follow" in user else user.get("following_count", 0),
            "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0) if "edge_owner_to_timeline_media" in user else user.get("media_count", 0),
            "is_private": user.get("is_private", False),
            "is_verified": user.get("is_verified", False),
            "profile_pic_url": user.get("profile_pic_url_hd", user.get("profile_pic_url", "")),
        }

    def _fetch_via_html(self, username: str) -> dict:
        """Fallback: Fetch profile page HTML and parse meta tags."""
        url = f"https://www.instagram.com/{username}/"

        resp = self.session.get(url, timeout=15)

        if resp.status_code == 404:
            raise Exception(f"Profile @{username} not found")
        if resp.status_code != 200:
            raise Exception(f"Got status {resp.status_code}")

        html = resp.text

        # Extract og:image (profile pic)
        profile_pic_url = ""
        og_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if og_match:
            profile_pic_url = og_match.group(1).replace("&amp;", "&")

        # Extract title for full name
        full_name = ""
        title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if title_match:
            name_match = re.match(r"^(.*?)\s*\(@", title_match.group(1))
            if name_match:
                full_name = name_match.group(1).strip()

        # Extract description for counts
        followers, following, posts = 0, 0, 0
        desc_match = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        if desc_match:
            desc = desc_match.group(1)
            f_match = re.search(r"([\d,.]+[KMB]?)\s*Followers", desc, re.IGNORECASE)
            fw_match = re.search(r"([\d,.]+[KMB]?)\s*Following", desc, re.IGNORECASE)
            p_match = re.search(r"([\d,.]+[KMB]?)\s*Posts", desc, re.IGNORECASE)
            if f_match:
                followers = parse_count(f_match.group(1))
            if fw_match:
                following = parse_count(fw_match.group(1))
            if p_match:
                posts = parse_count(p_match.group(1))

        if not profile_pic_url:
            raise Exception("Could not find profile pic in HTML")

        return {
            "username": username,
            "full_name": full_name,
            "bio": "",
            "followers": followers,
            "following": following,
            "posts": posts,
            "is_private": False,
            "is_verified": False,
            "profile_pic_url": profile_pic_url,
        }


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


# ============================================================
# Global session instance
# ============================================================
ig_session = InstagramSession()


@app.on_event("startup")
def startup():
    """Login to Instagram on app startup."""
    ig_user = os.environ.get("IG_USERNAME")
    ig_pass = os.environ.get("IG_PASSWORD")

    if ig_user and ig_pass:
        success = ig_session.login(ig_user, ig_pass)
        if success:
            print(f"🎉 App started with authenticated session (@{ig_user})")
        else:
            print("⚠️ Login failed. App will try unauthenticated methods.")
    else:
        print("⚠️ No IG credentials. Set IG_USERNAME and IG_PASSWORD env vars.")
        print("   The app will try to work without login but may be limited.")


# ============================================================
# Routes
# ============================================================

@app.get("/")
def root():
    return {
        "message": "Instagram Profile Photo Downloader API v3",
        "logged_in": ig_session.logged_in,
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
        data = ig_session.get_profile_data(username)

        # Download the actual profile pic image
        saved_path = None
        if data.get("profile_pic_url"):
            try:
                resp = ig_session.session.get(data["profile_pic_url"], timeout=15)
                if resp.status_code == 200:
                    saved_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")
                    with open(saved_path, "wb") as f:
                        f.write(resp.content)
            except Exception as e:
                print(f"⚠️ Could not download image: {e}")

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
    return {
        "status": "healthy",
        "version": "3.0.0",
        "logged_in": ig_session.logged_in,
        "login_user": ig_session.login_username,
    }
