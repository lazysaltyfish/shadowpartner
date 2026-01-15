"""Tests for storage hash prefix migration."""

import io

import pytest

from services.storage.local import LocalStorage


@pytest.fixture
def temp_storage(tmp_path):
    """Create a temporary storage instance."""
    storage = LocalStorage(root_dir=str(tmp_path / "storage"))
    return storage


def test_hash_prefix_extraction_upload_format(temp_storage):
    """Test that hash prefix is correctly extracted from upload_ identifier."""
    # Test with upload_ prefix
    assert (
        temp_storage._get_hash_prefix_path("upload_a1b2c3d4e5f6g7h8")
        == temp_storage.root_dir / "a1"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_0b1da1226270dde8")
        == temp_storage.root_dir / "0b"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_bb517e97b65b7274")
        == temp_storage.root_dir / "bb"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_3d89a87870bb511b")
        == temp_storage.root_dir / "3d"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_42bfd283baa4a417")
        == temp_storage.root_dir / "42"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_4664271160760e7d")
        == temp_storage.root_dir / "46"
    )
    assert (
        temp_storage._get_hash_prefix_path("upload_5c3b5d631c4c4df6")
        == temp_storage.root_dir / "5c"
    )


def test_hash_prefix_extraction_without_upload_prefix(temp_storage):
    """Test backward compatibility with non-upload_ identifiers."""
    # Test without upload_ prefix (backward compatibility)
    assert temp_storage._get_hash_prefix_path("a1b2c3d4") == temp_storage.root_dir / "a1"
    assert temp_storage._get_hash_prefix_path("ff123456") == temp_storage.root_dir / "ff"
    assert temp_storage._get_hash_prefix_path("00abcd") == temp_storage.root_dir / "00"


def test_hash_prefix_extraction_short_identifier(temp_storage):
    """Test with short identifiers."""
    # Test with short identifier (not starting with "upload_")
    # "up" is treated as regular identifier, so prefix is "up"
    assert temp_storage._get_hash_prefix_path("up") == temp_storage.root_dir / "up"
    # Single char identifier -> "00"
    assert temp_storage._get_hash_prefix_path("a") == temp_storage.root_dir / "00"
    # Two char identifier -> "ab"
    assert temp_storage._get_hash_prefix_path("ab") == temp_storage.root_dir / "ab"


def test_hash_prefix_extraction_mixed_case(temp_storage):
    """Test with mixed case identifiers."""
    # Test with mixed case (hex is case-insensitive)
    assert (
        temp_storage._get_hash_prefix_path("upload_A1B2C3D4E5F6G7H8")
        == temp_storage.root_dir / "A1"
    )
    assert temp_storage._get_hash_prefix_path("upload_FF00AA11") == temp_storage.root_dir / "FF"


@pytest.mark.asyncio
async def test_file_storage_structure(temp_storage):
    """Test that files are stored in correct hash prefix directories."""
    file_content = b"test content for storage"

    # Save file with upload_ identifier
    file_obj = io.BytesIO(file_content)
    identifier = "upload_a1b2c3d4e5f6g7h8"
    await temp_storage.save(file_obj, identifier)

    # Verify file location
    expected_path = temp_storage.root_dir / "a1" / identifier
    assert expected_path.exists(), f"File should be at {expected_path}"

    # Verify file exists
    assert await temp_storage.exists(identifier)

    # Verify file can be read
    with open(expected_path, "rb") as f:
        read_content = f.read()
    assert read_content == file_content

    # Cleanup
    await temp_storage.delete(identifier)
    assert not await temp_storage.exists(identifier)


@pytest.mark.asyncio
async def test_file_storage_different_prefixes(temp_storage):
    """Test that files with different hash prefixes go to different directories."""
    files = {
        "upload_0b1da1226270dde8": b"content 1",
        "upload_3d89a87870bb511b": b"content 2",
        "upload_bb517e97b65b7274": b"content 3",
    }

    # Save all files
    for identifier, content in files.items():
        file_obj = io.BytesIO(content)
        await temp_storage.save(file_obj, identifier)

    # Verify each file is in correct directory
    for identifier in files.keys():
        if identifier.startswith("upload_"):
            hash_part = identifier[7:]
            prefix = hash_part[:2]
        else:
            prefix = identifier[:2]

        expected_path = temp_storage.root_dir / prefix / identifier
        assert expected_path.exists(), f"File {identifier} should be at {expected_path}"

    # Verify all files exist
    for identifier in files.keys():
        assert await temp_storage.exists(identifier)

    # Cleanup
    for identifier in files.keys():
        await temp_storage.delete(identifier)


@pytest.mark.asyncio
async def test_storage_read_write_cycle(temp_storage):
    """Test complete read/write cycle with hash prefix structure."""
    original_content = b"This is test content for storage"

    # Write
    file_obj = io.BytesIO(original_content)
    identifier = "upload_ff00aa11bb22cc33"
    await temp_storage.save(file_obj, identifier)

    # Read
    read_file = await temp_storage.get(identifier)
    read_content = read_file.read()
    read_file.close()

    assert read_content == original_content

    # Cleanup
    await temp_storage.delete(identifier)


@pytest.mark.asyncio
async def test_storage_delete_removes_file(temp_storage):
    """Test that delete correctly removes files from hash prefix directories."""
    file_content = b"content to delete"
    file_obj = io.BytesIO(file_content)
    identifier = "upload_delete12345678"

    # Save file
    await temp_storage.save(file_obj, identifier)

    # Verify exists
    assert await temp_storage.exists(identifier)

    # Get file path before deletion
    hash_part = identifier[7:]
    prefix = hash_part[:2]
    file_path = temp_storage.root_dir / prefix / identifier

    assert file_path.exists()

    # Delete
    result = await temp_storage.delete(identifier)
    assert result is True

    # Verify removed
    assert not await temp_storage.exists(identifier)
    assert not file_path.exists()


def test_hash_prefix_distribution():
    """Test that hash prefixes are well distributed."""
    storage = LocalStorage(root_dir="/tmp/test_storage")

    # Simulate realistic hash distribution (random hex values)
    # Using different hash values to test prefix extraction
    test_hashes = [
        "0b1da1226270dde8",
        "a1b2c3d4e5f6g7h8",  # Note: using a mix for testing
        "ff1234567890abcd",
        "00abcdef12345678",
        "3d89a87870bb511b",
        "42bfd283baa4a417",
        "4664271160760e7d",
        "5c3b5d631c4c4df6",
        "bb517e97b65b7274",
        "cd11223344556677",
        "eef9988776655443",
        "9a88bb77cc665544",
    ]

    prefixes = set()
    for hash_hex in test_hashes:
        identifier = f"upload_{hash_hex}"
        path = storage._get_hash_prefix_path(identifier)
        prefix = path.name
        prefixes.add(prefix)

    # Should have different prefixes (not all the same)
    assert len(prefixes) > 8  # At least 8 different prefixes
    assert "up" not in prefixes  # Should not have "up" prefix
    # Verify some expected prefixes are present
    assert "0b" in prefixes
    assert "ff" in prefixes
