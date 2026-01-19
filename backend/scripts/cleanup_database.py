#!/usr/bin/env python3
"""Database cleanup script for ShadowPartner.

Detects and removes orphaned records and files:
- Orphaned SubtitleTracks (referencing non-existent assets)
- Orphaned VocabularyItems (referencing non-existent assets)
- Orphaned Assets (storage files missing)
- Orphaned Files (storage files without database records)
- Orphaned Users (no assets, optional age-based filtering)

Usage:
    python scripts/cleanup_database.py --dry-run --verbose
    python scripts/cleanup_database.py --force
    python scripts/cleanup_database.py --force --cleanup-orphaned-files --cleanup-orphaned-users
    python scripts/cleanup_database.py --force --cleanup-orphaned-users --user-age-threshold 7
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import services_registry
from db.engine import SessionLocal
from db.models import Asset, AssetType, SubtitleTrack, User, VocabularyItem
from settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Type alias for Session (using string to avoid circular imports)
Session = SessionLocal  # type: ignore[assignment, misc]


# Helper to access storage dynamically
def get_storage():
    return services_registry.storage


def parse_args():
    parser = argparse.ArgumentParser(
        description="Cleanup orphaned database records and storage files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run to see what would be deleted
  python cleanup_database.py --dry-run --verbose

  # Clean up orphaned subtitle tracks and assets only
  python cleanup_database.py --force

  # Clean up everything including orphaned files and users
  python cleanup_database.py --force --cleanup-orphaned-files --cleanup-orphaned-users

  # Clean up users older than 7 days with no assets
  python cleanup_database.py --force --cleanup-orphaned-users --user-age-threshold 7
        """,
    )

    # Safety flags
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually perform deletions (default: False)",
    )

    # Cleanup options
    parser.add_argument(
        "--cleanup-orphaned-files",
        action="store_true",
        help="Clean up orphaned storage files (files with no database record)",
    )
    parser.add_argument(
        "--cleanup-orphaned-users",
        action="store_true",
        help="Clean up orphaned users (users with no assets)",
    )
    parser.add_argument(
        "--user-age-threshold",
        type=int,
        default=30,
        help="Delete users older than this many days (default: 30)",
    )

    # Output control
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output with detailed information",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output, only show summary",
    )

    # Default behavior
    parser.set_defaults(dry_run=True)

    return parser.parse_args()


def detect_orphaned_subtitle_tracks(session: Session) -> List[SubtitleTrack]:
    """Find subtitle tracks that reference non-existent assets.

    This is a clear referential integrity violation and always safe to delete.

    Args:
        session: Database session

    Returns:
        List of orphaned subtitle tracks
    """
    all_tracks = session.query(SubtitleTrack).all()
    orphaned_tracks = []

    for track in all_tracks:
        asset = session.get(Asset, track.asset_id)
        if asset is None:
            orphaned_tracks.append(track)

    return orphaned_tracks


async def detect_orphaned_assets(session: SessionLocal) -> List[Asset]:
    """Find assets with missing storage files.

    Only checks UPLOAD type assets (YouTube assets have no storage file).

    Args:
        session: Database session

    Returns:
        List of assets with missing storage files
    """
    if get_storage() is None:
        logger.warning("Storage not initialized, skipping asset file check")
        return []

    upload_assets = (
        session.query(Asset)
        .filter(Asset.type == AssetType.UPLOAD)
        .filter(Asset.storage_path.isnot(None))
        .all()
    )

    orphaned_assets = []

    for asset in upload_assets:
        if asset.storage_path:
            exists = await get_storage().exists(asset.storage_path)
            if not exists:
                orphaned_assets.append(asset)

    return orphaned_assets


async def detect_orphaned_files(session: SessionLocal) -> List[str]:
    """Find storage files with no corresponding database record.

    Args:
        session: Database session

    Returns:
        List of orphaned storage file paths
    """
    if get_storage() is None:
        logger.warning("Storage not initialized, skipping file scan")
        return []

    # Get all storage paths from database (including thumbnails stored in meta)
    db_storage_paths = set()
    for asset in session.query(Asset).all():
        if asset.storage_path:
            db_storage_paths.add(asset.storage_path)
        if asset.meta and asset.meta.get("thumbnail_path"):
            db_storage_paths.add(asset.meta.get("thumbnail_path"))

    # Scan storage directory for actual files
    storage_root = Path(settings.storage_root_dir)
    orphaned_files = []

    if not storage_root.exists():
        return orphaned_files

    # Recursively find all upload_* files
    for file_path in storage_root.rglob("upload_*"):
        if file_path.is_file():
            # Convert to storage path format
            # File: data/storage/ab/upload_abc123... -> upload_abc123...
            relative_path = str(file_path.relative_to(storage_root))
            parts = relative_path.split("/")
            if len(parts) == 2 and parts[1].startswith("upload_"):
                file_storage_path = parts[1]
                if file_storage_path not in db_storage_paths:
                    orphaned_files.append(file_storage_path)

    return orphaned_files


def detect_orphaned_users(session: SessionLocal, age_threshold_days: int = 30) -> List[User]:
    """Find users with no assets, optionally filtered by age.

    Args:
        session: Database session
        age_threshold_days: Only delete users older than this (default: 30).
                           Set to 0 to skip age filtering.

    Returns:
        List of users with no assets (and older than threshold if specified)
    """
    all_users = session.query(User).all()
    orphaned_users = []

    threshold_date = None
    if age_threshold_days > 0:
        threshold_date = datetime.utcnow() - timedelta(days=age_threshold_days)

    for user in all_users:
        asset_count = session.query(Asset).filter(Asset.created_by == user.id).count()

        if asset_count == 0:
            if threshold_date is None or user.created_at < threshold_date:
                orphaned_users.append(user)

    return orphaned_users


def detect_orphaned_vocabulary(session: SessionLocal) -> List[VocabularyItem]:
    """Find vocabulary items that reference non-existent assets.

    This is a clear referential integrity violation and always safe to delete.

    Args:
        session: Database session

    Returns:
        List of orphaned vocabulary items
    """
    all_vocab = session.query(VocabularyItem).all()
    orphaned_vocab = []

    for vocab in all_vocab:
        asset = session.get(Asset, vocab.asset_id)
        if asset is None:
            orphaned_vocab.append(vocab)

    return orphaned_vocab


def cleanup_orphaned_vocabulary(
    session: SessionLocal, vocab_items: List[VocabularyItem], dry_run: bool
) -> int:
    """Clean up orphaned vocabulary items.

    Args:
        session: Database session
        vocab_items: List of orphaned vocabulary items to delete
        dry_run: If True, only report what would be deleted

    Returns:
        Number of vocabulary items deleted (or would be deleted in dry-run mode)
    """
    count = 0
    for vocab in vocab_items:
        if dry_run:
            logger.info(
                f"[DRY-RUN] Would delete orphaned vocabulary: "
                f"{vocab.id} (word={vocab.word}, asset_id={vocab.asset_id})"
            )
        else:
            logger.info(
                f"Deleting orphaned vocabulary: {vocab.id} "
                f"(word={vocab.word}, asset_id={vocab.asset_id})"
            )
            session.delete(vocab)
        count += 1

    if not dry_run and count > 0:
        session.commit()
        logger.info(f"Deleted {count} orphaned vocabulary items")

    return count


def cleanup_orphaned_tracks(
    session: SessionLocal, tracks: List[SubtitleTrack], dry_run: bool
) -> int:
    """Clean up orphaned subtitle tracks.

    Args:
        session: Database session
        tracks: List of orphaned tracks to delete
        dry_run: If True, only report what would be deleted

    Returns:
        Number of tracks deleted (or would be deleted in dry-run mode)
    """
    count = 0
    for track in tracks:
        if dry_run:
            logger.info(f"[DRY-RUN] Would delete orphaned track: {track.id}")
        else:
            logger.info(f"Deleting orphaned track: {track.id}")
            session.delete(track)
        count += 1

    if not dry_run and count > 0:
        session.commit()
        logger.info(f"Deleted {count} orphaned subtitle tracks")

    return count


def cleanup_orphaned_assets(session: SessionLocal, assets: List[Asset], dry_run: bool) -> int:
    """Clean up orphaned assets (missing storage files).

    Deleting asset will cascade to subtitle_tracks.

    Args:
        session: Database session
        assets: List of orphaned assets to delete
        dry_run: If True, only report what would be deleted

    Returns:
        Number of assets deleted (or would be deleted in dry-run mode)
    """
    count = 0
    for asset in assets:
        if dry_run:
            logger.info(
                f"[DRY-RUN] Would delete orphaned asset: "
                f"{asset.id} ({asset.type.value}:{asset.identifier})"
            )
        else:
            logger.info(
                f"Deleting orphaned asset: {asset.id} ({asset.type.value}:{asset.identifier})"
            )
            session.delete(asset)
        count += 1

    if not dry_run and count > 0:
        session.commit()
        logger.info(f"Deleted {count} orphaned assets (and their subtitle tracks)")

    return count


async def cleanup_orphaned_files(
    session: SessionLocal, file_paths: List[str], dry_run: bool
) -> int:
    """Clean up orphaned storage files.

    Args:
        session: Database session (unused but kept for consistent interface)
        file_paths: List of orphaned file paths to delete
        dry_run: If True, only report what would be deleted

    Returns:
        Number of files deleted (or would be deleted in dry-run mode)
    """
    count = 0
    for file_path in file_paths:
        if dry_run:
            logger.info(f"[DRY-RUN] Would delete orphaned file: {file_path}")
            count += 1
        else:
            logger.info(f"Deleting orphaned file: {file_path}")
            success = await get_storage().delete(file_path)
            if success:
                count += 1
            else:
                logger.warning(f"File not found (already deleted?): {file_path}")

    if not dry_run and count > 0:
        logger.info(f"Deleted {count} orphaned storage files")

    return count


def cleanup_orphaned_users(session: SessionLocal, users: List[User], dry_run: bool) -> int:
    """Clean up orphaned users.

    Args:
        session: Database session
        users: List of orphaned users to delete
        dry_run: If True, only report what would be deleted

    Returns:
        Number of users deleted (or would be deleted in dry-run mode)
    """
    count = 0
    for user in users:
        if dry_run:
            logger.info(
                f"[DRY-RUN] Would delete orphaned user: "
                f"{user.id} ({user.username or 'no username'})"
            )
        else:
            logger.info(f"Deleting orphaned user: {user.id} ({user.username or 'no username'})")
            session.delete(user)
        count += 1

    if not dry_run and count > 0:
        session.commit()
        logger.info(f"Deleted {count} orphaned users")

    return count


async def main():
    """Main cleanup execution."""
    args = parse_args()

    # Setup logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # Initialize storage
    services_registry.init_services()

    if get_storage() is None:
        logger.error("Storage initialization failed. Exiting.")
        return 1

    # Validate dry-run vs force
    if args.force:
        args.dry_run = False
        logger.warning("FORCE MODE ENABLED - Deletions will be executed!")
    else:
        args.dry_run = True
        logger.info("DRY-RUN MODE - No deletions will be performed")

    # Create database session
    session = SessionLocal()

    try:
        results = {
            "orphaned_tracks": 0,
            "orphaned_vocabulary": 0,
            "orphaned_assets": 0,
            "orphaned_files": 0,
            "orphaned_users": 0,
        }

        # Step 1: Detect and cleanup orphaned subtitle tracks
        logger.info("=" * 60)
        logger.info("Step 1: Detecting orphaned subtitle tracks...")
        orphaned_tracks = detect_orphaned_subtitle_tracks(session)
        logger.info(f"Found {len(orphaned_tracks)} orphaned subtitle tracks")

        if args.verbose and orphaned_tracks:
            for track in orphaned_tracks:
                logger.info(f"  - Track {track.id}: asset_id={track.asset_id}")

        results["orphaned_tracks"] = cleanup_orphaned_tracks(
            session, orphaned_tracks, dry_run=args.dry_run
        )

        # Step 2: Detect and cleanup orphaned vocabulary items
        logger.info("=" * 60)
        logger.info("Step 2: Detecting orphaned vocabulary items...")
        orphaned_vocab = detect_orphaned_vocabulary(session)
        logger.info(f"Found {len(orphaned_vocab)} orphaned vocabulary items")

        if args.verbose and orphaned_vocab:
            for vocab in orphaned_vocab:
                logger.info(f"  - Vocab {vocab.id}: word={vocab.word}, asset_id={vocab.asset_id}")

        results["orphaned_vocabulary"] = cleanup_orphaned_vocabulary(
            session, orphaned_vocab, dry_run=args.dry_run
        )

        # Step 3: Detect and cleanup orphaned assets
        logger.info("=" * 60)
        logger.info("Step 3: Detecting orphaned assets (missing files)...")
        orphaned_assets = await detect_orphaned_assets(session)
        logger.info(f"Found {len(orphaned_assets)} orphaned assets")

        if args.verbose and orphaned_assets:
            for asset in orphaned_assets:
                logger.info(
                    f"  - Asset {asset.id}: "
                    f"{asset.type.value}:{asset.identifier} "
                    f"(storage_path={asset.storage_path})"
                )

        results["orphaned_assets"] = cleanup_orphaned_assets(
            session, orphaned_assets, dry_run=args.dry_run
        )

        # Step 4: Detect and cleanup orphaned files (optional)
        if args.cleanup_orphaned_files:
            logger.info("=" * 60)
            logger.info("Step 4: Detecting orphaned storage files...")
            orphaned_files = await detect_orphaned_files(session)
            logger.info(f"Found {len(orphaned_files)} orphaned files")

            if args.verbose and orphaned_files:
                for file_path in orphaned_files:
                    logger.info(f"  - {file_path}")

            results["orphaned_files"] = await cleanup_orphaned_files(
                session, orphaned_files, dry_run=args.dry_run
            )
        else:
            logger.info("=" * 60)
            logger.info(
                "Step 4: Skipping orphaned file detection (use --cleanup-orphaned-files to enable)"
            )

        # Step 5: Detect and cleanup orphaned users (optional)
        if args.cleanup_orphaned_users:
            logger.info("=" * 60)
            logger.info(
                f"Step 5: Detecting orphaned users (older than {args.user_age_threshold} days)..."
            )
            orphaned_users = detect_orphaned_users(
                session, age_threshold_days=args.user_age_threshold
            )
            logger.info(f"Found {len(orphaned_users)} orphaned users")

            if args.verbose and orphaned_users:
                for user in orphaned_users:
                    logger.info(
                        f"  - User {user.id}: "
                        f"{user.username or 'no username'} "
                        f"(created: {user.created_at})"
                    )

            results["orphaned_users"] = cleanup_orphaned_users(
                session, orphaned_users, dry_run=args.dry_run
            )
        else:
            logger.info("=" * 60)
            logger.info(
                "Step 5: Skipping orphaned user detection (use --cleanup-orphaned-users to enable)"
            )

        # Print summary
        logger.info("=" * 60)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Mode: {'FORCE (executed)' if args.force else 'DRY-RUN (preview)'}")
        logger.info(f"Orphaned subtitle tracks deleted: {results['orphaned_tracks']}")
        logger.info(f"Orphaned vocabulary items deleted: {results['orphaned_vocabulary']}")
        logger.info(f"Orphaned assets deleted: {results['orphaned_assets']}")
        logger.info(f"Orphaned files deleted: {results['orphaned_files']}")
        logger.info(f"Orphaned users deleted: {results['orphaned_users']}")
        logger.info(f"Total records processed: {sum(results.values())}")
        logger.info("=" * 60)

        if args.dry_run:
            logger.info("To execute cleanup, run with --force flag")

        return 0

    except KeyboardInterrupt:
        logger.info("\nCleanup interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
