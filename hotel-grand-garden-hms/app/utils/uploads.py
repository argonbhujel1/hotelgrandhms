import os
import uuid
from flask import current_app


ALLOWED = {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED


def _upload_root() -> str:
    """Writable upload root: config UPLOAD_FOLDER ( /tmp on Vercel )."""
    root = current_app.config.get("UPLOAD_FOLDER") or "/tmp/hotel_hms_uploads"
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        root = "/tmp/hotel_hms_uploads"
        os.makedirs(root, exist_ok=True)
    return root


def save_upload(file_storage, subfolder: str) -> str | None:
    """Save image; return relative path uploads/... OR absolute URL is handled by cloudinary layer."""
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    if not allowed_file(file_storage.filename):
        raise ValueError("Only image files allowed (png, jpg, jpeg, gif, webp, svg, ico).")
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    name = f"{uuid.uuid4().hex[:12]}.{ext}"
    folder = os.path.join(_upload_root(), subfolder)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    file_storage.save(path)
    if not os.path.isfile(path):
        raise ValueError("Failed to save uploaded file.")
    # On Vercel files in /tmp are not publicly served via /static — prefer Cloudinary in production.
    return f"uploads/{subfolder}/{name}"
