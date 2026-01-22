"""Storage bridge for generating temporary access URLs for workers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class StorageBridge:
    """Bridge for generating pre-signed URLs for workers to access files.

    This provides temporary secure access to files in storage without
    requiring workers to have direct storage access.
    """

    def __init__(self, backend_base_url: str, ttl_seconds: int = 3600):
        self.backend_base_url = backend_base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        # Signatures stored as {path: (signature, expires_at)}
        self._signatures: Dict[str, Tuple[str, datetime]] = {}

    def generate_presigned_url(self, file_path: str, ttl_seconds: Optional[int] = None) -> str:
        """Generate a pre-signed URL for file access.

        Args:
            file_path: The storage path to generate URL for
            ttl_seconds: Optional custom TTL (defaults to instance TTL)

        Returns:
            A pre-signed URL that can be used to access the file
        """
        signature = secrets.token_urlsafe(32)
        ttl = ttl_seconds or self.ttl_seconds
        expires_at = datetime.now() + timedelta(seconds=ttl)

        self._signatures[file_path] = (signature, expires_at)

        url = f"{self.backend_base_url}/api/internal/temp-file?path={file_path}&sig={signature}"
        logger.debug(f"[StorageBridge] Generated presigned URL for: {file_path}")
        return url

    def validate_signature(self, file_path: str, signature: str) -> bool:
        """Validate a signature for file access.

        Args:
            file_path: The storage path being accessed
            signature: The signature to validate

        Returns:
            True if signature is valid and not expired
        """
        if file_path not in self._signatures:
            logger.warning(f"[StorageBridge] Unknown signature for path: {file_path}")
            return False

        stored_signature, expires_at = self._signatures[file_path]

        if datetime.now() > expires_at:
            logger.info(f"[StorageBridge] Expired signature for path: {file_path}")
            del self._signatures[file_path]
            return False

        # Use constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(signature, stored_signature):
            logger.warning(f"[StorageBridge] Invalid signature for path: {file_path}")
            return False

        return True

    def revoke_signature(self, file_path: str) -> bool:
        """Revoke a signature (e.g., after job completes).

        Args:
            file_path: The storage path to revoke access for

        Returns:
            True if signature was found and revoked
        """
        if file_path in self._signatures:
            del self._signatures[file_path]
            logger.debug(f"[StorageBridge] Revoked signature for: {file_path}")
            return True
        return False

    def cleanup_expired_signatures(self) -> int:
        """Remove expired signatures from memory.

        Returns:
            Number of signatures cleaned up
        """
        now = datetime.now()
        expired = [path for path, (_, expires_at) in self._signatures.items() if expires_at < now]

        for path in expired:
            del self._signatures[path]

        if expired:
            logger.info(f"[StorageBridge] Cleaned up {len(expired)} expired signatures")

        return len(expired)

    def get_signature_count(self) -> int:
        """Get the current number of active signatures."""
        return len(self._signatures)
