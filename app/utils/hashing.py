import hashlib
from pathlib import Path
from typing import BinaryIO, Union


def compute_sha256(data_or_path: Union[str, Path, bytes, BinaryIO], chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file path, bytes, or file-like object."""
    hasher = hashlib.sha256()

    if isinstance(data_or_path, bytes):
        hasher.update(data_or_path)
    elif isinstance(data_or_path, (str, Path)):
        file_path = Path(data_or_path)
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
    elif hasattr(data_or_path, "read"):
        # File-like object
        pos = 0
        if hasattr(data_or_path, "tell"):
            try:
                pos = data_or_path.tell()
            except Exception:
                pos = 0

        while chunk := data_or_path.read(chunk_size):
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            hasher.update(chunk)

        if hasattr(data_or_path, "seek"):
            try:
                data_or_path.seek(pos)
            except Exception:
                pass
    else:
        raise TypeError(f"Unsupported type for SHA-256 calculation: {type(data_or_path)}")

    return hasher.hexdigest()
