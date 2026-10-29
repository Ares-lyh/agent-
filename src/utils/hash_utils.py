"""Hash calculation and integrity verification utilities."""
import hashlib
import os
from typing import Union


def calculate_sha256(file_path: str) -> str:
    """Calculate the SHA-256 hash of a file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found for hash calculation: {file_path}")
    
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def calculate_content_sha256(content: Union[str, bytes]) -> str:
    """Calculate SHA-256 hash of an in-memory string or bytes."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def verify_file_hash(file_path: str, expected_hash: str) -> bool:
    """Verify if a file matches the expected SHA-256 hash."""
    if not os.path.exists(file_path):
        return False
    actual_hash = calculate_sha256(file_path)
    return actual_hash.lower() == expected_hash.lower()
