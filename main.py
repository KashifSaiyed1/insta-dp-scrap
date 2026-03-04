"""
Instagram Profile Photo Downloader - FastAPI Backend
=====================================================
Deployable on Render.com as a Web Service
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import instaloader
import os
import shutil

app = FastAPI(
    title="Instagram Profile Photo Downloader",
    description="Fetch profile photo & stats of any public Instagram account",
    version="1.0.0",
)

# Allow all origins (update this for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SAVE_DIR = "profile_photos"
os.makedirs(SAVE_DIR, exist_ok=True)


def get_loader():
    """Create a fresh Instaloader instance."""
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
    )


@app.get("/")
def root():
    return {
        "message": "Instagram Profile Photo Downloader API",
        "usage": "GET /profile/{username} for stats + photo URL",
        "docs": "Visit /docs for Swagger UI",
    }


@app.get("/profile/{username}")
def get_profile(username: str):
    """Fetch profile stats and download the profile photo."""

    username = username.strip().lstrip("@").lower()

    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")

    loader = get_loader()

    try:
        profile = instaloader.Profile.from_username(loader.context, username)

        # Download profile pic
        loader.download_profilepic(profile)

        # Move to our save directory
        saved_path = None
        src_folder = username
        if os.path.exists(src_folder):
            for file in os.listdir(src_folder):
                if file.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    src_path = os.path.join(src_folder, file)
                    dest_path = os.path.join(SAVE_DIR, f"{username}_profile_pic.jpg")
                    shutil.move(src_path, dest_path)
                    saved_path = dest_path
                    break
            # Clean up auto-created folder
            shutil.rmtree(src_folder, ignore_errors=True)

        return {
            "success": True,
            "username": username,
            "full_name": profile.full_name,
            "bio": profile.biography,
            "followers": profile.followers,
            "following": profile.followees,
            "posts": profile.mediacount,
            "is_private": profile.is_private,
            "is_verified": profile.is_verified,
            "profile_pic_url": profile.profile_pic_url,
            "download_url": f"/download/{username}" if saved_path else None,
        }

    except instaloader.exceptions.ProfileNotExistsException:
        raise HTTPException(status_code=404, detail=f"Profile '@{username}' does not exist")
    except instaloader.exceptions.ConnectionException as e:
        raise HTTPException(status_code=429, detail=f"Rate limited by Instagram. Try again later. {str(e)}")
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
    return {"status": "healthy"}
