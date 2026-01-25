"""Pytest configuration and fixtures for worker tests.

This module provides comprehensive fixtures for testing the GPU worker,
including environment setup, mocking external dependencies, and test data.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Stub whisper early to avoid GPU/torch initialization during test collection.
if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub.Whisper = object
    whisper_stub.load_model = MagicMock(return_value=MagicMock())
    sys.modules["whisper"] = whisper_stub

# ============================================================================
# Environment Setup
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any tests run."""
    # Set required environment variables for testing
    os.environ["BACKEND_WS_URL"] = "ws://localhost:8000/ws/worker"
    os.environ["WORKER_TOKEN"] = "test_worker_token"
    os.environ["WORKER_ID"] = "test-worker-01"
    os.environ["WHISPER_MODEL_SIZE"] = "base"
    os.environ["WHISPER_DEVICE"] = "cpu"  # Use CPU for tests
    os.environ["CUDA_VISIBLE_DEVICES"] = ""  # Disable CUDA in tests
    os.environ["PYTORCH_NO_CUDA"] = "1"  # Force torch to skip CUDA
    os.environ["WHISPER_FP16"] = "false"
    os.environ["AUDIO_CACHE_DIR"] = tempfile.gettempdir() + "/test_audio_cache"
    os.environ["MAX_CACHE_SIZE_GB"] = "1"

    yield

    # Cleanup: remove test cache directory if it exists
    import shutil
    cache_dir = os.environ.get("AUDIO_CACHE_DIR")
    if cache_dir and os.path.exists(cache_dir):
        try:
            shutil.rmtree(cache_dir)
        except OSError:
            pass


@pytest.fixture(scope="session", autouse=True)
def mock_asyncio_to_thread():
    """Mock asyncio.to_thread to prevent thread creation during tests.

    This prevents the tests from creating actual threads which can cause
    system freeze when tests don't properly clean up ThreadPoolExecutor instances.
    """
    import asyncio
    from unittest.mock import patch

    async def mock_to_thread_sync(func, *args, **kwargs):
        """Run sync function directly in the async context instead of thread."""
        return func(*args, **kwargs)

    with patch.object(asyncio, "to_thread", side_effect=mock_to_thread_sync):
        yield


@pytest.fixture(autouse=True)
def cleanup_thread_pools():
    """Automatically clean up any ThreadPoolExecutor instances after each test.

    This prevents thread leaks that can cause the system to freeze.
    """
    from concurrent.futures import ThreadPoolExecutor
    import gc
    import weakref

    # Track all ThreadPoolExecutor instances created during the test
    executors = []
    original_init = ThreadPoolExecutor.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        executors.append(weakref.ref(self))

    # Monkey patch to track executors
    ThreadPoolExecutor.__init__ = tracking_init

    yield

    # Restore original
    ThreadPoolExecutor.__init__ = original_init

    # Shutdown all tracked executors
    for ref in executors:
        executor = ref()
        if executor is not None:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass

    # Force garbage collection
    gc.collect()


# ============================================================================
# Temporary Directory Fixtures
# ============================================================================


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory for audio files.

    Returns:
        Path to temporary cache directory
    """
    cache_dir = tmp_path / "audio_cache"
    cache_dir.mkdir()
    return str(cache_dir)


@pytest.fixture
def temp_audio_file(tmp_path):
    """Create a temporary audio file for testing.

    Returns:
        Path to temporary audio file
    """
    audio_file = tmp_path / "test_audio.wav"
    # Create a minimal WAV file (44 bytes header + silence)
    with open(audio_file, "wb") as f:
        # Write minimal WAV header
        f.write(b"RIFF")
        f.write((36).to_bytes(4, "little"))  # file size - 8
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write((16).to_bytes(4, "little"))  # chunk size
        f.write((1).to_bytes(2, "little"))  # audio format (PCM)
        f.write((1).to_bytes(2, "little"))  # num channels
        f.write((44100).to_bytes(4, "little"))  # sample rate
        f.write((88200).to_bytes(4, "little"))  # byte rate
        f.write((2).to_bytes(2, "little"))  # block align
        f.write((16).to_bytes(2, "little"))  # bits per sample
        f.write(b"data")
        f.write((0).to_bytes(4, "little"))  # data size
    return str(audio_file)


# ============================================================================
# Mock Fixtures for External Dependencies
# ============================================================================


@pytest.fixture
def mock_whisper():
    """Mock the whisper module.

    Returns:
        MagicMock for whisper module
    """
    mock = MagicMock()
    mock_whisper_model = MagicMock()
    mock_whisper_model.transcribe = MagicMock(return_value={
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "こんにちは",
                "words": [
                    {"start": 0.0, "end": 1.0, "word": "こん"},
                    {"start": 1.0, "end": 2.0, "word": "こんにちは"},
                ],
            }
        ],
        "language": "ja",
        "language_probs": {},
    })
    mock.load_model = MagicMock(return_value=mock_whisper_model)
    return mock


@pytest.fixture
def mock_mecab():
    """Mock the MeCab module.

    Returns:
        MagicMock for MeCab module
    """
    mock = MagicMock()

    # Mock Tagger
    mock_tagger = MagicMock()

    # Mock Node for parseToNode chain
    mock_node_start = MagicMock()
    mock_node_start.surface = "こんにちは"
    mock_node_start.feature = "感動詞,*,*,*,*,*,*,コンニチハ,こんにちは,こんにちは"

    mock_node_end = MagicMock()
    mock_node_end.surface = ""  # Empty surface signals end

    # Set up the chain
    mock_node_start.next = mock_node_end
    mock_node_end.next = None

    mock_tagger.parseToNode = MagicMock(return_value=mock_node_start)
    mock.Tagger = MagicMock(return_value=mock_tagger)

    return mock


@pytest.fixture
def mock_ffmpeg():
    """Mock the ffmpeg module.

    Returns:
        MagicMock for ffmpeg module
    """
    mock = MagicMock()

    # Mock ffmpeg.input().output() chain
    mock_input = MagicMock()
    mock_output = MagicMock()
    mock_output.run = MagicMock()
    mock_output.overwrite_output = MagicMock(return_value=mock_output)
    mock_input.output = MagicMock(return_value=mock_output)
    mock.input = MagicMock(return_value=mock_input)

    # Mock ffmpeg.probe
    mock.probe = MagicMock(return_value={
        "format": {
            "duration": "10.5",
            "size": "1234567",
        },
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
            }
        ],
    })

    mock.input = mock_input
    return mock


@pytest.fixture
def mock_websockets():
    """Mock the websockets module.

    Returns:
        MagicMock for websockets module
    """
    mock = MagicMock()

    # Mock WebSocketClientProtocol
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock()
    mock_ws.close = AsyncMock()

    # Mock websockets.connect context manager
    mock_connect = AsyncMock()
    mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_connect.__aexit__ = AsyncMock()
    mock.connect = MagicMock(return_value=mock_connect)

    return mock


@pytest.fixture
def mock_aiohttp():
    """Mock the aiohttp module.

    Returns:
        MagicMock for aiohttp module
    """
    mock = MagicMock()

    # Mock ClientSession
    mock_session = AsyncMock()

    # Mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"content-length": "12345"}

    # Mock content iteration
    async def mock_chunks(size):
        """Mock chunked content iteration."""
        yield b"chunk1" * 1024
        yield b"chunk2" * 1024

    mock_response.content = MagicMock()
    mock_response.content.iter_chunked = MagicMock(return_value=mock_chunks(8192))

    # Mock session.get context manager
    mock_get = AsyncMock()
    mock_get.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get.__aexit__ = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_get)

    # Mock ClientSession context manager
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()

    mock.ClientSession = MagicMock(return_value=mock_session)

    return mock


# ============================================================================
# Module Stubbing for GPU Dependencies
# ============================================================================


@pytest.fixture
def stub_gpu_dependencies(monkeypatch):
    """Stub out GPU dependencies for CPU-only testing.

    This fixture patches whisper and related modules to avoid GPU requirements.

    Args:
        monkeypatch: pytest monkeypatch fixture
    """
    # Create mock modules
    mock_whisper_module = MagicMock()
    mock_whisper_module.load_model = MagicMock(return_value=MagicMock())

    # Patch lazy loader to avoid importing real whisper.
    monkeypatch.setattr("transcriber._load_whisper", lambda: mock_whisper_module)

    return mock_whisper_module


# ============================================================================
# Async Event Loop Fixture
# ============================================================================


@pytest.fixture
def event_loop():
    """Create an event loop for async tests.

    This fixture ensures each test gets a fresh event loop.

    Returns:
        New asyncio event loop
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Common Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_job_data():
    """Create sample job assignment data.

    Returns:
        Dict representing a job assignment message
    """
    return {
        "type": "job_assigned",
        "job_id": "test-job-123",
        "audio_url": "https://example.com/audio/test.wav",
        "options": {
            "language": "ja",
            "model_size": "base",
            "fp16": False,
            "thumbnail": True,
            "thumbnail_timestamp": 1.0,
            "analysis_texts": ["テスト", "分析"],
        },
    }


@pytest.fixture
def sample_transcription_result():
    """Create sample transcription result.

    Returns:
        Dict representing a transcription result
    """
    return {
        "segments": [
            {
                "start": 0.0,
                "end": 2.5,
                "text": "こんにちは、世界",
                "words": [
                    {"word": "こん", "start": 0.0, "end": 0.5},
                    {"word": "こんにちは", "start": 0.5, "end": 1.5},
                    {"word": "世界", "start": 1.5, "end": 2.5},
                ],
            },
            {
                "start": 2.5,
                "end": 5.0,
                "text": "これはテストです",
                "words": [
                    {"word": "これ", "start": 2.5, "end": 3.0},
                    {"word": "は", "start": 3.0, "end": 3.2},
                    {"word": "テスト", "start": 3.2, "end": 4.0},
                    {"word": "です", "start": 4.0, "end": 5.0},
                ],
            },
        ],
        "language": "ja",
        "language_probs": {
            "ja": 0.95,
            "en": 0.03,
            "zh": 0.02,
        },
    }


@pytest.fixture
def sample_mecab_tokens():
    """Create sample MeCab analysis tokens.

    Returns:
        List of token dicts representing MeCab output
    """
    return [
        {"text": "これ", "reading": "これ"},
        {"text": "は", "reading": "は"},
        {"text": "テスト", "reading": "てすと"},
        {"text": "です", "reading": "です"},
    ]


@pytest.fixture
def sample_websocket_messages():
    """Create sample WebSocket messages for testing.

    Returns:
        Dict of message types to sample message dicts
    """
    return {
        "register": {
            "type": "register",
            "token": "test_worker_token",
            "worker_id": "test-worker-01",
            "capabilities": {
                "model": "base",
                "device": "cpu",
                "fp16": False,
            },
        },
        "registered": {
            "type": "registered",
            "worker_id": "test-worker-01",
        },
        "job_assigned": {
            "type": "job_assigned",
            "job_id": "test-job-123",
            "audio_url": "https://example.com/audio.wav",
            "options": {
                "language": "ja",
            },
        },
        "job_complete": {
            "type": "job_complete",
            "job_id": "test-job-123",
            "result": {
                "segments": [],
                "language": "ja",
            },
        },
        "job_complete_ack": {
            "type": "job_complete_ack",
            "job_id": "test-job-123",
        },
        "job_failed": {
            "type": "job_failed",
            "job_id": "test-job-123",
            "error": "Test error message",
        },
        "job_progress": {
            "type": "job_progress",
            "job_id": "test-job-123",
            "progress": 50,
            "message": "Transcribing...",
        },
        "heartbeat": {
            "type": "heartbeat",
        },
        "heartbeat_ack": {
            "type": "heartbeat_ack",
        },
        "error": {
            "type": "error",
            "message": "Server error message",
        },
    }


# ============================================================================
# Async Test Configuration
# ============================================================================


# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)


@pytest_asyncio.fixture
async def async_mock_websocket():
    """Create an async mock WebSocket for testing.

    Returns:
        AsyncMock WebSocket with send/recv methods
    """
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock()
    mock_ws.close = AsyncMock()

    # Set up message queue for recv
    message_queue = asyncio.Queue()

    async def mock_recv():
        return await message_queue.get()

    mock_ws.recv = mock_recv
    mock_ws.message_queue = message_queue

    return mock_ws
