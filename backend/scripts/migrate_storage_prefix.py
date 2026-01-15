#!/usr/bin/env python3
"""Storage prefix migration script.

Migrates files from the old incorrect "up/" directory to the correct
hash-based prefix directories.

Example:
    upload_0b1da1226270dde8 (in up/) -> 0b/upload_0b1da1226270dde8
    upload_3d89a87870bb511b (in up/) -> 3d/upload_3d89a87870bb511b
"""

import shutil
from pathlib import Path


def migrate_storage_files():
    """Migrate files from up/ to correct hash prefix directories."""
    # Change to backend directory
    backend_dir = Path(__file__).parent.parent
    storage_root = backend_dir / "data" / "storage"
    old_dir = storage_root / "up"

    migrated_count = 0
    failed_files = []

    print(f"Storage root: {storage_root}")
    print(f"Old directory: {old_dir}")

    if not old_dir.exists():
        print(f"\n✓ No migration needed: {old_dir} does not exist")
        return

    # Find all upload_* files in up/ directory
    upload_files = list(old_dir.glob("upload_*"))

    if not upload_files:
        print(f"\n✓ No upload files found in {old_dir}")
        return

    print(f"\nFound {len(upload_files)} files to migrate\n")

    for file_path in upload_files:
        try:
            identifier = file_path.name

            # Extract hash prefix
            if identifier.startswith("upload_"):
                hash_part = identifier[7:]  # Remove "upload_" prefix
                prefix = hash_part[:2] if len(hash_part) >= 2 else "00"
            else:
                print(f"  Skipping non-upload file: {identifier}")
                continue

            # Create new directory
            new_dir = storage_root / prefix
            new_dir.mkdir(parents=True, exist_ok=True)

            # Move file
            new_path = new_dir / identifier
            shutil.move(str(file_path), str(new_path))

            print(f"  ✓ Migrated: {identifier} -> {prefix}/")
            migrated_count += 1

        except Exception as e:
            print(f"  ✗ Failed to migrate {file_path.name}: {e}")
            failed_files.append(file_path.name)

    # Clean up empty directory
    if old_dir.exists() and not list(old_dir.iterdir()):
        old_dir.rmdir()
        print(f"\n✓ Removed empty directory: {old_dir}")

    # Summary
    print(f"\n{'=' * 60}")
    print("Migration complete:")
    print(f"  - Successfully migrated: {migrated_count} files")
    if failed_files:
        print(f"  - Failed: {len(failed_files)} files")
        for name in failed_files:
            print(f"    - {name}")
    print(f"{'=' * 60}")

    # Show new directory structure
    print("\nNew directory structure:")
    for prefix_dir in sorted(storage_root.iterdir()):
        if prefix_dir.is_dir():
            file_count = len(list(prefix_dir.glob("upload_*")))
            print(f"  {prefix_dir.name}/: {file_count} files")


if __name__ == "__main__":
    migrate_storage_files()
