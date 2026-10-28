"""Store uploaded files and generated artifacts on the local filesystem."""

import os
import uuid
from typing import BinaryIO, Tuple

from core.config import BASE_URL, LOCAL_UPLOAD_DIR
from utility.string_methods import sanitize_filename


def store_file(name: str, content: bytes) -> Tuple[str, str]:
    """Save generated content locally and return its streaming URL and file ID."""
    safe_name = sanitize_filename(name)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
    dest_path = os.path.join(LOCAL_UPLOAD_DIR, unique_name)
    with open(dest_path, "wb") as output:
        output.write(content)
    return f"{BASE_URL}/api/stream/{unique_name}", unique_name


def store_file_stream(name: str, stream: BinaryIO) -> Tuple[str, str]:
    """Stream an upload to local disk, enforcing MAX_FILE_SIZE and cleaning up failures."""
    from core.config import MAX_FILE_SIZE

    safe_name = sanitize_filename(name)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
    dest_path = os.path.join(LOCAL_UPLOAD_DIR, unique_name)
    total = 0
    try:
        with open(dest_path, "wb") as output:
            while True:
                data = stream.read(1024 * 1024)
                if not data:
                    break
                total += len(data)
                if total > MAX_FILE_SIZE:
                    raise RuntimeError("MAX_FILE_SIZE_EXCEEDED")
                output.write(data)
        return f"{BASE_URL}/api/stream/{unique_name}", unique_name
    except Exception as error:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        if str(error) == "MAX_FILE_SIZE_EXCEEDED":
            from fastapi import HTTPException

            raise HTTPException(status_code=413, detail="File exceeds the configured size limit.")
        raise
