"""Tests for config.py"""

import os
import pytest
from dataclasses import FrozenInstanceError
from pathlib import Path

from config import Config, load_config, get_capabilities


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Hide .env file and clean environment for isolated tests."""
    # Temporarily move .env file if it exists
    env_path = Path(__file__).parent.parent / ".env"
    temp_backup = tmp_path / ".env.backup"

    if env_path.exists():
        env_path.rename(temp_backup)

    yield

    # Restore .env file
    if temp_backup.exists():
        temp_backup.rename(env_path)


class TestConfigDataclass:
    """Test Config dataclass properties."""

    def test_frozen_dataclass(self):
        """Config should be a frozen dataclass (immutable)."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=10,
        )

        with pytest.raises(FrozenInstanceError):
            config.worker_id = "gpu-02"

    def test_all_fields_present(self):
        """Config should have all required fields."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=10,
        )

        assert hasattr(config, "backend_ws_url")
        assert hasattr(config, "worker_token")
        assert hasattr(config, "worker_id")
        assert hasattr(config, "whisper_model_size")
        assert hasattr(config, "whisper_device")
        assert hasattr(config, "whisper_fp16")
        assert hasattr(config, "audio_cache_dir")
        assert hasattr(config, "max_cache_size_gb")


class TestLoadConfig:
    """Test load_config() function."""

    def test_loads_from_environment_variables(self, clean_env, monkeypatch):
        """Should load all config values from environment variables."""
        monkeypatch.setenv("BACKEND_WS_URL", "ws://example.com:9000/ws/worker")
        monkeypatch.setenv("WORKER_TOKEN", "secret-token-123")
        monkeypatch.setenv("WORKER_ID", "gpu-worker-05")
        monkeypatch.setenv("WHISPER_MODEL_SIZE", "large")
        monkeypatch.setenv("WHISPER_DEVICE", "cpu")
        monkeypatch.setenv("WHISPER_FP16", "true")
        monkeypatch.setenv("AUDIO_CACHE_DIR", "/tmp/audio-cache")
        monkeypatch.setenv("MAX_CACHE_SIZE_GB", "50")

        config = load_config()

        assert config.backend_ws_url == "ws://example.com:9000/ws/worker"
        assert config.worker_token == "secret-token-123"
        assert config.worker_id == "gpu-worker-05"
        assert config.whisper_model_size == "large"
        assert config.whisper_device == "cpu"
        assert config.whisper_fp16 is True
        assert config.audio_cache_dir == "/tmp/audio-cache"
        assert config.max_cache_size_gb == 50

    def test_uses_correct_defaults_for_optional_values(self, clean_env, monkeypatch):
        """Should use correct defaults when optional env vars are not set."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")
        # Clear all other env vars to test defaults
        monkeypatch.delenv("BACKEND_WS_URL", raising=False)
        monkeypatch.delenv("WORKER_ID", raising=False)
        monkeypatch.delenv("WHISPER_MODEL_SIZE", raising=False)
        monkeypatch.delenv("WHISPER_DEVICE", raising=False)
        monkeypatch.delenv("WHISPER_FP16", raising=False)
        monkeypatch.delenv("AUDIO_CACHE_DIR", raising=False)
        monkeypatch.delenv("MAX_CACHE_SIZE_GB", raising=False)

        config = load_config()

        assert config.backend_ws_url == "ws://localhost:8000/ws/worker"
        assert config.worker_id == "gpu-01"
        assert config.whisper_model_size == "base"
        assert config.whisper_device == "cuda"
        assert config.whisper_fp16 is False
        assert config.audio_cache_dir == "./cache/audio"
        assert config.max_cache_size_gb == 10

    def test_raises_value_error_when_worker_token_missing(self, clean_env, monkeypatch):
        """Should raise ValueError when WORKER_TOKEN is missing."""
        monkeypatch.delenv("WORKER_TOKEN", raising=False)

        with pytest.raises(ValueError, match="WORKER_TOKEN environment variable is required"):
            load_config()

    def test_raises_value_error_when_worker_token_empty_string(self, clean_env, monkeypatch):
        """Should raise ValueError when WORKER_TOKEN is empty string."""
        monkeypatch.setenv("WORKER_TOKEN", "")

        with pytest.raises(ValueError, match="WORKER_TOKEN environment variable is required"):
            load_config()

    def test_parses_whisper_fp16_as_boolean_correctly(self, monkeypatch):
        """Should parse WHISPER_FP16 as boolean correctly."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")

        # Test various true values
        for true_value in ["true", "True", "TRUE", "tRuE"]:
            monkeypatch.setenv("WHISPER_FP16", true_value)
            config = load_config()
            assert config.whisper_fp16 is True

        # Test various false values
        for false_value in ["false", "False", "FALSE", "anything"]:
            monkeypatch.setenv("WHISPER_FP16", false_value)
            config = load_config()
            assert config.whisper_fp16 is False

    def test_parses_max_cache_size_gb_as_integer_correctly(self, monkeypatch):
        """Should parse MAX_CACHE_SIZE_GB as integer correctly."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")

        test_values = [0, 1, 10, 100, 999]
        for value in test_values:
            monkeypatch.setenv("MAX_CACHE_SIZE_GB", str(value))
            config = load_config()
            assert config.max_cache_size_gb == value
            assert isinstance(config.max_cache_size_gb, int)


class TestLoadConfigRobustness:
    """Test load_config() robustness with edge cases."""

    def test_invalid_integer_values_for_max_cache_size_gb(self, monkeypatch):
        """Should raise ValueError for invalid integer values."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")

        invalid_values = ["abc", "10.5", "1e5", "null", "", " "]
        for invalid_value in invalid_values:
            monkeypatch.setenv("MAX_CACHE_SIZE_GB", invalid_value)
            with pytest.raises(ValueError):
                load_config()

    def test_negative_integer_for_max_cache_size_gb(self, monkeypatch):
        """Should accept negative integers (validation is caller's responsibility)."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")
        monkeypatch.setenv("MAX_CACHE_SIZE_GB", "-5")

        config = load_config()
        assert config.max_cache_size_gb == -5

    def test_empty_strings_vs_missing_values(self, monkeypatch):
        """Should treat empty strings differently from missing values."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")

        # Empty string for optional values should be accepted
        monkeypatch.setenv("BACKEND_WS_URL", "")
        monkeypatch.setenv("WORKER_ID", "")
        monkeypatch.setenv("WHISPER_MODEL_SIZE", "")
        monkeypatch.setenv("WHISPER_DEVICE", "")
        monkeypatch.setenv("AUDIO_CACHE_DIR", "")

        config = load_config()

        assert config.backend_ws_url == ""
        assert config.worker_id == ""
        assert config.whisper_model_size == ""
        assert config.whisper_device == ""
        assert config.audio_cache_dir == ""

    def test_whitespace_in_environment_variables(self, monkeypatch):
        """Should preserve whitespace in string environment variables."""
        monkeypatch.setenv("WORKER_TOKEN", " test-token ")
        monkeypatch.setenv("WORKER_ID", " gpu-01 ")
        monkeypatch.setenv("BACKEND_WS_URL", " ws://localhost:8000/ws/worker ")

        config = load_config()

        # Whitespace is preserved for string values
        assert config.worker_token == " test-token "
        assert config.worker_id == " gpu-01 "
        assert config.backend_ws_url == " ws://localhost:8000/ws/worker "

    def test_unicode_in_worker_id_and_other_strings(self, monkeypatch):
        """Should handle Unicode characters in string values."""
        monkeypatch.setenv("WORKER_TOKEN", "token-测试-123")
        monkeypatch.setenv("WORKER_ID", "worker-日本語-01")
        monkeypatch.setenv("AUDIO_CACHE_DIR", "/tmp/缓存")

        config = load_config()

        assert config.worker_token == "token-测试-123"
        assert config.worker_id == "worker-日本語-01"
        assert config.audio_cache_dir == "/tmp/缓存"

    def test_special_characters_in_strings(self, monkeypatch):
        """Should handle special characters in string values."""
        monkeypatch.setenv("WORKER_TOKEN", "token@#$%^&*()")
        monkeypatch.setenv("BACKEND_WS_URL", "ws://example.com:8000/ws/worker?query=1&key=2")

        config = load_config()

        assert config.worker_token == "token@#$%^&*()"
        assert config.backend_ws_url == "ws://example.com:8000/ws/worker?query=1&key=2"

    def test_whitespace_handling_in_boolean(self, clean_env, monkeypatch):
        """Should not strip whitespace in boolean value (actual behavior)."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")

        # Whitespace is NOT stripped, so " true " != "true"
        monkeypatch.setenv("WHISPER_FP16", " true ")
        config = load_config()
        assert config.whisper_fp16 is False  # " true ".lower() != "true"

        monkeypatch.setenv("WHISPER_FP16", " false ")
        config = load_config()
        assert config.whisper_fp16 is False  # " false ".lower() != "true"

        # Only exact match works
        monkeypatch.setenv("WHISPER_FP16", "true")
        config = load_config()
        assert config.whisper_fp16 is True

        monkeypatch.setenv("WHISPER_FP16", "false")
        config = load_config()
        assert config.whisper_fp16 is False

    def test_zero_values(self, monkeypatch):
        """Should handle zero values correctly."""
        monkeypatch.setenv("WORKER_TOKEN", "test-token")
        monkeypatch.setenv("MAX_CACHE_SIZE_GB", "0")
        monkeypatch.setenv("WHISPER_FP16", "false")

        config = load_config()

        assert config.max_cache_size_gb == 0
        assert config.whisper_fp16 is False


class TestGetCapabilities:
    """Test get_capabilities() function."""

    def test_returns_correct_capability_dict_structure(self):
        """Should return dict with correct structure."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size="large",
            whisper_device="cuda",
            whisper_fp16=True,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=50,
        )

        capabilities = get_capabilities(config)

        assert isinstance(capabilities, dict)
        assert "model" in capabilities
        assert "device" in capabilities
        assert "fp16" in capabilities

    def test_capability_values_match_config(self):
        """Capability values should match corresponding config values."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size="medium",
            whisper_device="cpu",
            whisper_fp16=False,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=20,
        )

        capabilities = get_capabilities(config)

        assert capabilities["model"] == "medium"
        assert capabilities["device"] == "cpu"
        assert capabilities["fp16"] is False

    def test_capability_dict_does_not_include_all_config(self):
        """Capabilities dict should only include specific fields, not entire config."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="secret-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=True,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=10,
        )

        capabilities = get_capabilities(config)

        # Should NOT include sensitive or non-capability fields
        assert "backend_ws_url" not in capabilities
        assert "worker_token" not in capabilities
        assert "worker_id" not in capabilities
        assert "audio_cache_dir" not in capabilities
        assert "max_cache_size_gb" not in capabilities

    @pytest.mark.parametrize(
        "model,device,fp16",
        [
            ("tiny", "cuda", True),
            ("base", "cuda", False),
            ("small", "cpu", False),
            ("medium", "cuda", True),
            ("large", "cuda", True),
            ("large-v2", "cuda", False),
        ],
    )
    def test_various_whisper_configurations(self, model, device, fp16):
        """Should handle various Whisper model configurations."""
        config = Config(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size=model,
            whisper_device=device,
            whisper_fp16=fp16,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=10,
        )

        capabilities = get_capabilities(config)

        assert capabilities["model"] == model
        assert capabilities["device"] == device
        assert capabilities["fp16"] == fp16
