import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Insta-API-Direct")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15",
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*"
}

@app.get("/profile/{username}")
async def get_profile(username: str):
    username = username.strip().lstrip("@").lower()
    api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    
    async with httpx.AsyncClient() as client:
        try:
            # Adding a referrer helps look more authentic
            client.headers.update({"Referer": f"https://www.instagram.com/{username}/"})
            response = await client.get(api_url, headers=HEADERS, timeout=10.0)
            
            if response.status_code != 200:
                return {"success": False, "error": f"Instagram blocked us (Status: {response.status_code})"}

            data = response.json()
            user = data.get("data", {}).get("user")
            
            if not user:
                return {"success": False, "error": "User not found"}

            return {
                "success": True,
                "full_name": user.get("full_name"),
                "followers": user.get("edge_followed_by", {}).get("count"),
                "hd_profile_pic": user.get("profile_pic_url_hd"),
                "bio": user.get("biography"),
                # We provide a link to our proxy route below
                "proxy_image": f"/proxy-image?url={user.get('profile_pic_url_hd')}"
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/proxy-image")
async def proxy_image(url: str):
    """Fetches the image so the browser doesn't get blocked by Instagram's CDN policy."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        return Response(content=resp.content, media_type="image/jpeg")

@app.get("/")
def health():
    return {"status": "running"}