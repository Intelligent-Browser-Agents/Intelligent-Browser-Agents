from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from aiofiles import open as aio_open
from aiofiles.os import makedirs, remove


class EvidenceManager:
    """Manages storage, versioning, and retention of evidence files.

    Evidence files (screenshots, DOM snapshots) are stored with hashed filenames
    for security and versioned for retry tracking. Automatic cleanup enforces
    retention policies.
    """

    def __init__(
        self,
        *,
        evidence_dir: str | Path = "evidence",
        retention_days: int = 7,
    ) -> None:
        """Initialize the evidence manager.

        Args:
            evidence_dir: Base directory for storing evidence files.
            retention_days: Number of days to retain evidence files before cleanup.
        """
        self.evidence_dir = Path(evidence_dir)
        self.retention_days = retention_days
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Create evidence directory if it doesn't exist."""
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def _generate_hash(self, task_id: UUID, timestamp: datetime, version: int = 1) -> str:
        """Generate a hash for evidence filename.

        Args:
            task_id: Task identifier.
            timestamp: Timestamp of the action.
            version: Version number for retries (1, 2, 3, ...).

        Returns:
            Hexadecimal hash string.
        """
        content = f"{task_id}{timestamp.isoformat()}{version}".encode()
        return hashlib.sha256(content).hexdigest()[:16]

    async def store_evidence(
        self,
        *,
        task_id: UUID,
        timestamp: datetime,
        content: bytes | str,
        file_type: str = "png",
        version: int = 1,
    ) -> Path:
        """Store evidence content to disk with hashed filename.

        Args:
            task_id: Task identifier.
            timestamp: Timestamp of the action.
            content: File content (bytes for binary, str for text).
            file_type: File extension (png, html, txt, etc.).
            version: Version number for retries.

        Returns:
            Path to the stored evidence file.
        """
        hash_str = self._generate_hash(task_id, timestamp, version)
        filename = f"evidence_{version}.{file_type}" if version > 1 else f"evidence.{file_type}"
        filepath = self.evidence_dir / hash_str / filename

        # Create subdirectory for this hash
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        if isinstance(content, str):
            async with aio_open(filepath, "w", encoding="utf-8") as f:
                await f.write(content)
        else:
            async with aio_open(filepath, "wb") as f:
                await f.write(content)

        return filepath

    def get_evidence_path(
        self,
        *,
        task_id: UUID,
        timestamp: datetime,
        file_type: str = "png",
        version: int = 1,
    ) -> Optional[Path]:
        """Get the expected path for an evidence file.

        Args:
            task_id: Task identifier.
            timestamp: Timestamp of the action.
            file_type: File extension.
            version: Version number.

        Returns:
            Path if file exists, None otherwise.
        """
        hash_str = self._generate_hash(task_id, timestamp, version)
        filename = f"evidence_{version}.{file_type}" if version > 1 else f"evidence.{file_type}"
        filepath = self.evidence_dir / hash_str / filename

        return filepath if filepath.exists() else None

    async def store_screenshot(
        self,
        *,
        task_id: UUID,
        timestamp: datetime,
        screenshot_data: bytes,
        version: int = 1,
    ) -> Path:
        """Store screenshot evidence.

        Args:
            task_id: Task identifier.
            timestamp: Timestamp of the action.
            screenshot_data: PNG image bytes.
            version: Version number for retries.

        Returns:
            Path to stored screenshot.
        """
        return await self.store_evidence(
            task_id=task_id,
            timestamp=timestamp,
            content=screenshot_data,
            file_type="png",
            version=version,
        )

    async def store_dom_snapshot(
        self,
        *,
        task_id: UUID,
        timestamp: datetime,
        dom_content: str,
        version: int = 1,
    ) -> Path:
        """Store DOM snapshot as HTML file.

        Args:
            task_id: Task identifier.
            timestamp: Timestamp of the action.
            dom_content: HTML content string.
            version: Version number for retries.

        Returns:
            Path to stored DOM snapshot.
        """
        return await self.store_evidence(
            task_id=task_id,
            timestamp=timestamp,
            content=dom_content,
            file_type="html",
            version=version,
        )

    async def cleanup_expired(self) -> int:
        """Remove evidence files older than retention period.

        Returns:
            Number of files removed.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed_count = 0

        if not self.evidence_dir.exists():
            return 0

        for hash_dir in self.evidence_dir.iterdir():
            if not hash_dir.is_dir():
                continue

            # Check directory modification time as proxy for file age
            dir_mtime = datetime.fromtimestamp(
                hash_dir.stat().st_mtime, tz=timezone.utc
            )

            if dir_mtime < cutoff_date:
                # Remove entire hash directory
                for file in hash_dir.rglob("*"):
                    if file.is_file():
                        await remove(str(file))
                        removed_count += 1
                hash_dir.rmdir()

        return removed_count

    def get_storage_stats(self) -> dict:
        """Get statistics about evidence storage.

        Returns:
            Dictionary with storage statistics.
        """
        if not self.evidence_dir.exists():
            return {
                "total_files": 0,
                "total_size_mb": 0.0,
                "directories": 0,
            }

        total_files = 0
        total_size = 0
        directories = 0

        for item in self.evidence_dir.rglob("*"):
            if item.is_file():
                total_files += 1
                total_size += item.stat().st_size
            elif item.is_dir() and item != self.evidence_dir:
                directories += 1

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "directories": directories,
            "retention_days": self.retention_days,
        }

