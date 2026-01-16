"""Unit tests for LocalStorage implementation."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

from services.storage.local import LocalStorage

# ==================== Basic Operations ====================


@pytest.mark.asyncio
async def test_local_storage_save():
    """Test saving file to local storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)
        content = b"test content"

        # Save
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "test_file.txt")

        assert path == "test_file.txt"

        # Verify file exists
        assert await storage.exists(path)

        # Verify content
        retrieved = await storage.get(path)
        try:
            assert retrieved.read() == content
        finally:
            retrieved.close()


@pytest.mark.asyncio
async def test_local_storage_save_with_hash_prefix():
    """Test hash-based directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save with upload_ prefix
        content = b"test"
        file_obj = io.BytesIO(content)
        await storage.save(file_obj, "upload_a1b2c3d4e5f6g7h8")

        # Verify hash prefix directory structure
        # Should be in tmpdir/a1/upload_a1b2c3d4e5f6g7h8
        expected_path = Path(tmpdir) / "a1" / "upload_a1b2c3d4e5f6g7h8"
        assert expected_path.exists()


@pytest.mark.asyncio
async def test_local_storage_save_overwrite():
    """Test overwriting existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save initial file
        content1 = b"initial content"
        file_obj1 = io.BytesIO(content1)
        await storage.save(file_obj1, "overwrite.txt")

        # Overwrite with new content
        content2 = b"new content"
        file_obj2 = io.BytesIO(content2)
        await storage.save(file_obj2, "overwrite.txt")

        # Verify new content
        retrieved = await storage.get("overwrite.txt")
        try:
            assert retrieved.read() == content2
        finally:
            retrieved.close()


# ==================== Delete Operations ====================


@pytest.mark.asyncio
async def test_local_storage_delete():
    """Test deleting file from local storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save file
        file_obj = io.BytesIO(b"test content")
        path = await storage.save(file_obj, "test_delete.txt")

        # Delete
        success = await storage.delete(path)
        assert success is True

        # Verify gone
        exists = await storage.exists(path)
        assert exists is False


@pytest.mark.asyncio
async def test_local_storage_delete_nonexistent():
    """Test deleting non-existent file returns False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        success = await storage.delete("non_existent.txt")
        assert success is False


@pytest.mark.asyncio
async def test_local_storage_delete_cleanup_empty_dirs():
    """Test that empty parent directories are cleaned up."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save file
        file_obj = io.BytesIO(b"test content")
        path = await storage.save(file_obj, "upload_a1b2c3d4e5f6g7h8")

        # Get hash prefix directory path
        hash_prefix_dir = Path(tmpdir) / "a1"
        assert hash_prefix_dir.exists()

        # Delete file
        await storage.delete(path)

        # Verify empty directory removed
        # Note: root_dir should not be removed
        assert not hash_prefix_dir.exists()
        assert Path(tmpdir).exists()


# ==================== Exists and Get Full Path ====================


@pytest.mark.asyncio
async def test_local_storage_exists():
    """Test checking file existence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Check non-existent file
        exists = await storage.exists("non_existent.txt")
        assert exists is False

        # Save file and check exists
        file_obj = io.BytesIO(b"test content")
        await storage.save(file_obj, "exists_test.txt")
        exists = await storage.exists("exists_test.txt")
        assert exists is True


@pytest.mark.asyncio
async def test_local_storage_get_full_path():
    """Test getting full filesystem path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        await storage.save(io.BytesIO(b"content"), "upload_a1b2c3d4e5f6g7h8")

        full_path = await storage.get_full_path("upload_a1b2c3d4e5f6g7h8")

        # Should be tmpdir/a1/upload_a1b2c3d4e5f6g7h8
        expected = Path(tmpdir) / "a1" / "upload_a1b2c3d4e5f6g7h8"
        assert str(full_path) == str(expected)


# ==================== File Size Tests ====================


@pytest.mark.asyncio
async def test_local_storage_get_file_size():
    """Test getting file size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save file
        content = b"x" * 1000  # 1000 bytes
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "test_size.txt")

        # Get size
        size = await storage.get_file_size(path)
        assert size == 1000


@pytest.mark.asyncio
async def test_local_storage_get_file_size_empty():
    """Test getting size of empty file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save empty file
        file_obj = io.BytesIO(b"")
        path = await storage.save(file_obj, "empty.txt")

        # Get size
        size = await storage.get_file_size(path)
        assert size == 0


@pytest.mark.asyncio
async def test_local_storage_get_file_size_nonexistent():
    """Test that FileNotFoundError is raised for non-existent files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        with pytest.raises(FileNotFoundError):
            await storage.get_file_size("non_existent.txt")


# ==================== MIME Type Tests ====================


@pytest.mark.asyncio
async def test_local_storage_get_mime_type():
    """Test MIME type detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Test various extensions
        assert await storage.get_mime_type("test.mp4") == "video/mp4"
        assert await storage.get_mime_type("test.mp3") == "audio/mpeg"
        assert await storage.get_mime_type("test.pdf") == "application/pdf"
        assert await storage.get_mime_type("test.png") == "image/png"


@pytest.mark.asyncio
async def test_local_storage_get_mime_type_unknown():
    """Test MIME type for unknown extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        mime_type = await storage.get_mime_type("test.unknown")
        assert mime_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_local_storage_get_mime_type_no_extension():
    """Test MIME type for file without extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        mime_type = await storage.get_mime_type("README")
        assert mime_type == "application/octet-stream"


# ==================== Get Operations ====================


@pytest.mark.asyncio
async def test_local_storage_get():
    """Test getting file content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save file with various content
        content = b"Hello, World!"
        file_obj = io.BytesIO(content)
        await storage.save(file_obj, "get_test.txt")

        # Get file
        retrieved = await storage.get("get_test.txt")
        try:
            assert retrieved.read() == content
        finally:
            retrieved.close()


@pytest.mark.asyncio
async def test_local_storage_get_binary_content():
    """Test getting binary file content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save binary file
        content = bytes(range(256))  # Binary data
        file_obj = io.BytesIO(content)
        await storage.save(file_obj, "binary.bin")

        # Get file
        retrieved = await storage.get("binary.bin")
        try:
            assert retrieved.read() == content
        finally:
            retrieved.close()


@pytest.mark.asyncio
async def test_local_storage_get_nonexistent():
    """Test that FileNotFoundError is raised for non-existent files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        with pytest.raises(FileNotFoundError):
            await storage.get("non_existent.txt")


# ==================== Concurrent and Edge Cases ====================


@pytest.mark.asyncio
async def test_local_storage_concurrent_operations():
    """Test concurrent save/get operations."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Create multiple tasks
        async def save_and_get(index):
            content = f"content {index}".encode()
            file_obj = io.BytesIO(content)
            path = await storage.save(file_obj, f"concurrent_{index}.txt")
            retrieved = await storage.get(path)
            try:
                return retrieved.read()
            finally:
                retrieved.close()

        # Run concurrent operations
        tasks = [save_and_get(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify all succeeded
        for i, result in enumerate(results):
            assert result == f"content {i}".encode()


@pytest.mark.asyncio
async def test_local_storage_directory_structure():
    """Test hash-based directory structure is created correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save files with different hash prefixes
        files_to_save = [
            ("upload_a1b2c3", "a1"),
            ("upload_d4e5f6", "d4"),
            ("upload_g7h8i9", "g7"),
        ]

        for identifier, expected_prefix in files_to_save:
            file_obj = io.BytesIO(b"content")
            await storage.save(file_obj, identifier)

            # Verify prefix directory created
            prefix_dir = Path(tmpdir) / expected_prefix
            assert prefix_dir.exists()

            # Verify file in correct directory
            file_path = prefix_dir / identifier
            assert file_path.exists()


@pytest.mark.asyncio
async def test_local_storage_special_chars_in_content():
    """Test saving files with special characters in content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Save file with special characters
        content = b"Test \x00\x01\x02\x03 content\nLine 1\r\nLine 2\tTab"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "special_chars.txt")

        # Get and verify
        retrieved = await storage.get(path)
        try:
            assert retrieved.read() == content
        finally:
            retrieved.close()


# ==================== iter_file() Tests ====================


@pytest.mark.asyncio
async def test_local_storage_iter_file_full():
    """Test iterating entire file in chunks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        # Create a file larger than default chunk size
        content = b"x" * 25000  # 25KB (larger than 8192 chunk size)
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "iter_full.bin")

        # Iterate and collect
        chunks = []
        async for chunk in storage.iter_file(path, chunk_size=8192):
            chunks.append(chunk)

        # Verify content
        reconstructed = b"".join(chunks)
        assert reconstructed == content


@pytest.mark.asyncio
async def test_local_storage_iter_file_range_start_only():
    """Test iterating from start byte to end of file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789" * 100  # 1000 bytes
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "iter_range_start.bin")

        # Iterate from byte 100 to end
        chunks = []
        async for chunk in storage.iter_file(path, start=100, chunk_size=8192):
            chunks.append(chunk)

        # Verify content (should skip first 100 bytes)
        reconstructed = b"".join(chunks)
        assert reconstructed == content[100:]


@pytest.mark.asyncio
async def test_local_storage_iter_file_range_start_and_end():
    """Test iterating from start byte to end byte (inclusive)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789" * 100  # 1000 bytes
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "iter_range_both.bin")

        # Iterate from byte 100 to byte 199 (inclusive)
        chunks = []
        async for chunk in storage.iter_file(path, start=100, end=199, chunk_size=8192):
            chunks.append(chunk)

        # Verify content (100 bytes)
        reconstructed = b"".join(chunks)
        assert reconstructed == content[100:200]  # end is inclusive
        assert len(reconstructed) == 100


@pytest.mark.asyncio
async def test_local_storage_iter_file_single_byte():
    """Test iterating a single byte."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "single_byte.bin")

        # Iterate byte at index 5
        chunks = []
        async for chunk in storage.iter_file(path, start=5, end=5):
            chunks.append(chunk)

        # Verify single byte
        reconstructed = b"".join(chunks)
        assert reconstructed == b"5"
        assert len(reconstructed) == 1


@pytest.mark.asyncio
async def test_local_storage_iter_file_empty_range():
    """Test that empty range (start > end) returns no chunks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "empty_range.bin")

        # Iterate with invalid range (start > end)
        chunks = []
        async for chunk in storage.iter_file(path, start=10, end=5):
            chunks.append(chunk)

        # Should be empty
        assert len(chunks) == 0


@pytest.mark.asyncio
async def test_local_storage_iter_file_custom_chunk_size():
    """Test iterating with custom chunk sizes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"x" * 100
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "custom_chunk.bin")

        # Iterate with small chunk size
        chunks = []
        async for chunk in storage.iter_file(path, chunk_size=7):
            chunks.append(chunk)

        # Verify we got the right number of chunks
        assert len(chunks) == 15  # 100 / 7 = 14.28 -> 15 chunks
        assert b"".join(chunks) == content


@pytest.mark.asyncio
async def test_local_storage_iter_file_large_chunk_size():
    """Test iterating with chunk size larger than file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"small file"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "large_chunk.bin")

        # Iterate with huge chunk size
        chunks = []
        async for chunk in storage.iter_file(path, chunk_size=100000):
            chunks.append(chunk)

        # Should get single chunk
        assert len(chunks) == 1
        assert chunks[0] == content


@pytest.mark.asyncio
async def test_local_storage_iter_file_nonexistent():
    """Test that iterating non-existent file raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        with pytest.raises(FileNotFoundError):
            async for _ in storage.iter_file("nonexistent.bin"):
                pass


@pytest.mark.asyncio
async def test_local_storage_iter_file_exactly_at_file_size():
    """Test iterating starting exactly at file size boundary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "boundary.bin")

        # Start at file size (should return nothing)
        chunks = []
        async for chunk in storage.iter_file(path, start=10):
            chunks.append(chunk)

        assert len(chunks) == 0


@pytest.mark.asyncio
async def test_local_storage_iter_file_boundary_conditions():
    """Test various boundary conditions for range requests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"0123456789" * 100  # 1000 bytes
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "boundary_test.bin")

        # Test 1: start = 0, end = 0 (first byte)
        chunks = []
        async for chunk in storage.iter_file(path, start=0, end=0):
            chunks.append(chunk)
        assert b"".join(chunks) == content[0:1]

        # Test 2: start = 0, end = 999 (entire file)
        chunks = []
        async for chunk in storage.iter_file(path, start=0, end=999):
            chunks.append(chunk)
        assert b"".join(chunks) == content

        # Test 3: start = 999, end = 999 (last byte)
        chunks = []
        async for chunk in storage.iter_file(path, start=999, end=999):
            chunks.append(chunk)
        assert b"".join(chunks) == content[999:1000]


@pytest.mark.asyncio
async def test_local_storage_iter_file_multiple_consumers():
    """Test that iter_file generator can be consumed multiple times if regenerated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"x" * 100
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "multi_consumer.bin")

        # Consume first time
        chunks1 = []
        async for chunk in storage.iter_file(path):
            chunks1.append(chunk)

        # Consume second time (new generator)
        chunks2 = []
        async for chunk in storage.iter_file(path):
            chunks2.append(chunk)

        # Both should have same content
        assert b"".join(chunks1) == content
        assert b"".join(chunks2) == content


# ==================== Error Handling and Edge Cases ====================


@pytest.mark.asyncio
async def test_local_storage_delete_fails_gracefully():
    """Test that delete returns False for non-existent files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        success = await storage.delete("does_not_exist.bin")
        assert success is False


@pytest.mark.asyncio
async def test_local_storage_concurrent_deletes():
    """Test concurrent delete operations on same file."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        file_obj = io.BytesIO(b"content")
        path = await storage.save(file_obj, "concurrent_del.bin")

        async def delete_task():
            return await storage.delete(path)

        results = await asyncio.gather(delete_task(), delete_task(), delete_task())

        success_count = sum(1 for r in results if r)
        assert success_count == 1


@pytest.mark.asyncio
async def test_local_storage_large_file():
    """Test handling of large files (>1MB)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"x" * (2 * 1024 * 1024)
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "large_file.bin")

        size = await storage.get_file_size(path)
        assert size == 2 * 1024 * 1024

        chunks = []
        async for chunk in storage.iter_file(path):
            chunks.append(chunk)
        assert b"".join(chunks) == content


@pytest.mark.asyncio
async def test_local_storage_overwrite_during_iteration():
    """Test iterating file while another process overwrites it."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content1 = b"initial content " * 1000
        file_obj = io.BytesIO(content1)
        path = await storage.save(file_obj, "overwrite_test.bin")

        async def iterate_partial():
            chunks = []
            async for chunk in storage.iter_file(path, chunk_size=100):
                chunks.append(chunk)
                if len(chunks) >= 3:
                    break
            return chunks

        iterate_task = asyncio.create_task(iterate_partial())

        await asyncio.sleep(0.01)
        content2 = b"new content " * 1000
        file_obj2 = io.BytesIO(content2)
        await storage.save(file_obj2, path)

        chunks = await iterate_task

        total_bytes = sum(len(c) for c in chunks)
        assert total_bytes > 0


@pytest.mark.asyncio
async def test_local_storage_delete_nonexistent_prefix():
    """Test deleting files from non-existent hash prefix directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        success = await storage.delete("zz_file.bin")
        assert success is False


@pytest.mark.asyncio
async def test_local_storage_save_same_path_concurrently():
    """Test saving to same path concurrently."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        async def save_task(index):
            content = f"content {index}".encode()
            file_obj = io.BytesIO(content)
            return await storage.save(file_obj, "concurrent_save.bin")

        results = await asyncio.gather(save_task(1), save_task(2), save_task(3))

        assert len(set(results)) >= 1

        assert await storage.exists("concurrent_save.bin")


@pytest.mark.asyncio
async def test_local_storage_get_after_delete():
    """Test getting file after it's deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        file_obj = io.BytesIO(b"content")
        path = await storage.save(file_obj, "get_after_del.bin")

        retrieved = await storage.get(path)
        try:
            assert retrieved.read() == b"content"
        finally:
            retrieved.close()

        await storage.delete(path)

        with pytest.raises(FileNotFoundError):
            await storage.get(path)


@pytest.mark.asyncio
async def test_local_storage_iter_after_delete():
    """Test iterating file after it's deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        file_obj = io.BytesIO(b"content")
        path = await storage.save(file_obj, "iter_after_del.bin")

        await storage.delete(path)

        with pytest.raises(FileNotFoundError):
            async for _ in storage.iter_file(path):
                pass


@pytest.mark.asyncio
async def test_local_storage_get_file_size_after_delete():
    """Test getting file size after it's deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        file_obj = io.BytesIO(b"content")
        path = await storage.save(file_obj, "size_after_del.bin")
        size = await storage.get_file_size(path)
        assert size == 7

        await storage.delete(path)

        with pytest.raises(FileNotFoundError):
            await storage.get_file_size(path)


@pytest.mark.asyncio
async def test_local_storage_special_path_characters():
    """Test handling of paths with special characters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        special_paths = [
            "test_file with spaces.bin",
            "test-file_with-dashes.bin",
            "test_file.with.dots.bin",
            "test_file_123.bin",
        ]

        for path in special_paths:
            content = f"content for {path}".encode()
            file_obj = io.BytesIO(content)
            saved_path = await storage.save(file_obj, path)

            retrieved = await storage.get(saved_path)
            try:
                assert retrieved.read() == content
            finally:
                retrieved.close()


@pytest.mark.asyncio
async def test_local_storage_empty_directory_cleanup():
    """Test that deleting last file in prefix dir removes the directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(root_dir=tmpdir)

        content = b"content"
        file_obj = io.BytesIO(content)
        path = await storage.save(file_obj, "upload_aabbccddeeff.bin")

        prefix_dir = Path(tmpdir) / "aa"
        assert prefix_dir.exists()

        await storage.delete(path)

        assert not prefix_dir.exists()
        assert Path(tmpdir).exists()
