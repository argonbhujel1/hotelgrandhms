"""Upload images/videos to Cloudinary when configured; else local static/uploads."""
from __future__ import annotations
import os
from flask import current_app


def cloudinary_enabled() -> bool:
    return bool(
        current_app.config.get("CLOUDINARY_CLOUD_NAME")
        and current_app.config.get("CLOUDINARY_API_KEY")
        and current_app.config.get("CLOUDINARY_API_SECRET")
    ) or bool(current_app.config.get("CLOUDINARY_URL"))


def upload_media(file_storage, folder: str = "hms") -> dict | None:
    """
    Returns dict: {url, public_id, resource_type} or None if no file.
    Falls back to local path under static/uploads.
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    if cloudinary_enabled():
        import cloudinary
        import cloudinary.uploader
        cfg = {
            "cloud_name": current_app.config.get("CLOUDINARY_CLOUD_NAME"),
            "api_key": current_app.config.get("CLOUDINARY_API_KEY"),
            "api_secret": current_app.config.get("CLOUDINARY_API_SECRET"),
        }
        if current_app.config.get("CLOUDINARY_URL"):
            cloudinary.config(cloudinary_url=current_app.config["CLOUDINARY_URL"])
        else:
            cloudinary.config(**cfg)
        result = cloudinary.uploader.upload(
            file_storage,
            folder=f"hotel-grand/{folder}",
            resource_type="auto",
        )
        return {
            "url": result.get("secure_url") or result.get("url"),
            "public_id": result.get("public_id"),
            "resource_type": result.get("resource_type", "image"),
        }
    # Local fallback
    from app.utils.uploads import save_upload
    path = save_upload(file_storage, folder)
    if not path:
        return None
    return {"url": None, "local_path": path, "public_id": None, "resource_type": "image"}


def media_src(image_url: str | None, image_path: str | None) -> str:
    """Prefer Cloudinary URL, else static path."""
    if image_url:
        return image_url
    if image_path:
        if image_path.startswith("http"):
            return image_path
        from flask import url_for
        try:
            return url_for("static", filename=image_path)
        except Exception:
            return f"/static/{image_path}"
    return ""
