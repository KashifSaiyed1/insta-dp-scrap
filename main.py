import os
import httpx
import re
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Instagram HD Profile Downloader",
    description="Stealth API method using Session Cookies",
    version="6.0.0"
)

# Allow your frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This pulls the long string you pasted into Render's Environment Variables
IG_COOKIE = os.getenv("IG_COOKIE", "")

# Standard Mobile Headers to look like a real iPhone
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Cookie": IG_COOKIE
}

@app.get("/")
def health_check():
    return {"status": "online", "authenticated": bool(IG_COOKIE)}

@app.get("/profile/{username}")
async def get_profile(username: str):
    """
    Fetches high-res profile data using the internal Instagram API.
    """
    username = username.strip().lstrip("@").lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    
    # We update the Referer for every request to match the specific profile
    current_headers = HEADERS.copy()
    current_headers["Referer"] = f"https://www.instagram.com/{username}/"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(api_url, headers=current_headers, timeout=10.0)
            
            if response.status_code == 429:
                return {
                    "success": False, 
                    "error": "Rate limited. Your IG_COOKIE might be flagged or expired."
                }
            
            if response.status_code != 200:
                return {
                    "success": False, 
                    "error": f"Instagram returned status code: {response.status_code}"
                }

            data = response.json()
            user = data.get("data", {}).get("user")
            
            if not user:
                return {"success": False, "error": "User not found or profile is restricted."}

            # Prepare the clean data response
            return {
                "success": True,
                "username": user.get("username"),
                "full_name": user.get("full_name"),
                "bio": user.get("biography"),
                "followers": user.get("edge_followed_by", {}).get("count"),
                "following": user.get("edge_follow", {}).get("count"),
                "posts": user.get("edge_owner_to_timeline_media", {}).get("count"),
                "is_private": user.get("is_private"),
                "is_verified": user.get("is_verified"),
                "hd_profile_pic": user.get("profile_pic_url_hd"),
                # This link allows you to bypass Instagram's "broken image" block
                "proxy_image_url": f"/proxy-image?url={user.get('profile_pic_url_hd')}"
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/proxy-image")
async def proxy_image(url: str):
    """
    Acts as a bridge to show the Instagram photo on your website.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
        
    async with httpx.AsyncClient() as client:
        try:
            # We must use a User-Agent to fetch the image from Instagram's CDN
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0)
            if resp.status_code == 200:
                return Response(content=resp.content, media_type="image/jpeg")
            else:
                raise HTTPException(status_code=resp.status_code, detail="Could not fetch image from CDN")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")