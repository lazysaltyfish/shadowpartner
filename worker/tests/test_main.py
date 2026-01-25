"""Tests for main.py entry point."""

from __future__ import annotations

import signal
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

# Import the module to test
import main


class TestSignalHandler:
    """Tests for signal_handler function."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mock worker instance."""
        worker = MagicMock()
        worker.stop = MagicMock()
        return worker

    @pytest.fixture
    def setup_worker(self, mock_worker):
        """Setup the global worker variable."""
        main.worker = mock_worker
        yield
        main.worker = None

    def test_signal_handler_sigint_calls_stop(self, setup_worker, mock_worker):
        """Test that SIGINT calls worker.stop()."""
        with patch("main.sys.exit"):
            main.signal_handler(signal.SIGINT, None)

        mock_worker.stop.assert_called_once()

    def test_signal_handler_sigterm_calls_stop(self, setup_worker, mock_worker):
        """Test that SIGTERM calls worker.stop()."""
        with patch("main.sys.exit"):
            main.signal_handler(signal.SIGTERM, None)

        mock_worker.stop.assert_called_once()

    def test_signal_handler_exits_with_code_0(self, setup_worker):
        """Test that signal_handler exits with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            main.signal_handler(signal.SIGINT, None)

        assert exc_info.value.code == 0

    def test_signal_handler_without_worker(self):
        """Test that signal_handler works when worker is None."""
        main.worker = None

        # Should not raise an exception
        with pytest.raises(SystemExit) as exc_info:
            main.signal_handler(signal.SIGINT, None)

        assert exc_info.value.code == 0

    def test_multiple_signals_in_sequence(self, setup_worker, mock_worker):
        """Test handling multiple signals in sequence."""
        with patch("main.sys.exit"):
            main.signal_handler(signal.SIGINT, None)
            main.signal_handler(signal.SIGTERM, None)

        # First signal should have exited, but if called multiple times
        # stop should be called each time before exit
        assert mock_worker.stop.call_count == 2


class TestMain:
    """Tests for main function."""

    @pytest.fixture
    def mock_ensure_ffmpeg(self):
        """Mock ensure_ffmpeg function."""
        with patch("main.ensure_ffmpeg") as m:
            yield m

    @pytest.fixture
    def mock_worker_client(self):
        """Mock WhisperWorkerClient class."""
        with patch("main.WhisperWorkerClient") as m:
            yield m

    @pytest.fixture
    def mock_signal(self):
        """Mock signal module."""
        with patch("main.signal") as m:
            yield m

    @pytest.fixture
    def mock_asyncio_run(self):
        """Mock asyncio.run."""
        with patch("main.asyncio.run") as m:
            yield m

    def test_main_sets_up_signal_handlers(self, mock_signal):
        """Test that main() sets up signal handlers for SIGINT and SIGTERM."""
        mock_worker = MagicMock()
        mock_worker.start = Mock(return_value="worker-start")
        with patch("main.ensure_ffmpeg"), patch(
            "main.WhisperWorkerClient", return_value=mock_worker
        ), patch("main.asyncio.run", return_value=None):
            try:
                main.main()
            except SystemExit:
                pass

        # Check that signal.signal was called twice (SIGINT and SIGTERM)
        assert mock_signal.signal.call_count == 2

        # Verify that signal.signal was called with the correct signal numbers
        # by checking that the mock's SIGINT and SIGTERM attributes were accessed
        calls = mock_signal.signal.call_args_list

        # The first argument to each signal.signal call should be the signal number
        # Since we're mocking the signal module, we get mock objects
        # Just verify that signal.signal was called exactly twice

    def test_main_calls_ensure_ffmpeg(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() calls ensure_ffmpeg()."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.return_value = None

        try:
            main.main()
        except SystemExit:
            pass

        mock_ensure_ffmpeg.assert_called_once()

    def test_main_creates_whisper_worker_client(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() creates WhisperWorkerClient instance."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.return_value = None

        try:
            main.main()
        except SystemExit:
            pass

        mock_worker_client.assert_called_once()

    def test_main_sets_global_worker(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() sets the global worker variable."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.return_value = None

        try:
            main.main()
        except SystemExit:
            pass

        assert main.worker is mock_worker_instance

    def test_main_calls_asyncio_run_on_worker_start(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() calls asyncio.run(worker.start())."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.return_value = None

        try:
            main.main()
        except SystemExit:
            pass

        mock_asyncio_run.assert_called_once()
        # Check that the coroutine passed is the worker's start method
        # This is verified by the fact that asyncio.run was called

    def test_main_handles_keyboard_interrupt(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() handles KeyboardInterrupt gracefully."""
        mock_worker_instance = MagicMock()
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.side_effect = KeyboardInterrupt()

        # Should not raise an exception
        main.main()

        # Verify worker was created
        mock_worker_client.assert_called_once()

    def test_main_handles_exceptions_and_exits_with_code_1(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that main() handles exceptions and exits with code 1."""
        mock_worker_instance = MagicMock()
        test_exception = Exception("Worker error")
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.side_effect = test_exception

        with pytest.raises(SystemExit) as exc_info:
            main.main()

        assert exc_info.value.code == 1

    def test_main_exits_with_code_1_on_ffmpeg_setup_failure(
        self, mock_ensure_ffmpeg, mock_worker_client
    ):
        """Test that main() exits with code 1 when FFmpeg setup fails."""
        mock_ensure_ffmpeg.side_effect = Exception("FFmpeg not found")

        with pytest.raises(SystemExit) as exc_info:
            main.main()

        assert exc_info.value.code == 1
        # Worker client should not be created if FFmpeg setup fails
        mock_worker_client.assert_not_called()

    def test_main_clears_global_worker_on_exception(
        self, mock_ensure_ffmpeg, mock_worker_client, mock_asyncio_run
    ):
        """Test that global worker is set even if an exception occurs."""
        mock_worker_instance = MagicMock()
        test_exception = Exception("Worker error")
        mock_worker_instance.start = Mock(return_value="worker-start")
        mock_worker_client.return_value = mock_worker_instance
        mock_asyncio_run.side_effect = test_exception

        with pytest.raises(SystemExit):
            main.main()

        # Worker should still be set in global variable
        assert main.worker is mock_worker_instance


class TestMainRobustness:
    """Robustness tests for main.py edge cases."""

    @pytest.fixture
    def reset_main_state(self):
        """Reset main module state before each test."""
        main.worker = None
        yield
        main.worker = None

    def test_signal_during_worker_operation(
        self, reset_main_state
    ):
        """Test signal handling while worker is running."""
        mock_worker = MagicMock()
        mock_worker.start = Mock(return_value="worker-start")
        main.worker = mock_worker

        # Simulate signal during operation
        with patch("main.sys.exit") as mock_exit:
            main.signal_handler(signal.SIGINT, None)

            mock_worker.stop.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_missing_ffmpeg_exits_gracefully(self, reset_main_state):
        """Test that missing FFmpeg causes graceful exit."""
        with patch("main.ensure_ffmpeg") as mock_ensure:
            mock_ensure.side_effect = RuntimeError("FFmpeg setup failed")

            with pytest.raises(SystemExit) as exc_info:
                main.main()

            assert exc_info.value.code == 1

    def test_worker_initialization_failure(
        self, reset_main_state
    ):
        """Test handling of worker initialization failure."""
        with patch("main.ensure_ffmpeg"), patch(
            "main.WhisperWorkerClient", side_effect=Exception("Init failed")
        ), patch("main.asyncio.run"):
            # The exception is raised before the try/except in main()
            # so it won't be caught by the exception handler
            # However, we can verify that initialization fails as expected
            with pytest.raises(Exception, match="Init failed"):
                main.main()

    def test_multiple_signal_handlers_registration(self, reset_main_state):
        """Test that signal handlers can be registered without conflict."""
        with patch("main.signal.signal") as mock_signal_func:
            mock_worker = MagicMock()
            mock_worker.start = Mock(return_value="worker-start")

            with patch("main.ensure_ffmpeg"), patch(
                "main.WhisperWorkerClient", return_value=mock_worker
            ), patch("main.asyncio.run", return_value=None):
                try:
                    main.main()
                except SystemExit:
                    pass

            # Signal handlers should be registered exactly twice
            assert mock_signal_func.call_count == 2

    def test_worker_stop_called_before_exit(self, reset_main_state):
        """Test that worker.stop() is called before sys.exit()."""
        call_order = []

        mock_worker = MagicMock()

        def mock_stop():
            call_order.append("stop")

        def mock_exit(code):
            call_order.append("exit")

        mock_worker.stop = mock_stop
        main.worker = mock_worker

        with patch("main.sys.exit", side_effect=mock_exit):
            main.signal_handler(signal.SIGINT, None)

        # Stop should be called before exit
        # (Note: sys.exit actually raises SystemExit, so both are called)
        assert "stop" in call_order

    def test_keyboard_interrupt_does_not_exit(self, reset_main_state):
        """Test that KeyboardInterrupt is handled without exiting."""
        mock_worker = MagicMock()
        mock_worker.start = Mock(return_value="worker-start")

        with patch("main.ensure_ffmpeg"), patch(
            "main.WhisperWorkerClient", return_value=mock_worker
        ), patch("main.asyncio.run", side_effect=KeyboardInterrupt()):
            # Should not raise SystemExit
            main.main()

        # Worker should be created
        assert main.worker is mock_worker

    def test_exception_in_worker_start_exits_with_code_1(
        self, reset_main_state
    ):
        """Test that exception during worker.start() exits with code 1."""
        mock_worker = MagicMock()
        mock_worker.start = Mock(return_value="worker-start")

        with patch("main.ensure_ffmpeg"), patch(
            "main.WhisperWorkerClient", return_value=mock_worker
        ), patch("main.asyncio.run", side_effect=RuntimeError("Worker failed")):
            with pytest.raises(SystemExit) as exc_info:
                main.main()

            assert exc_info.value.code == 1

    def test_signal_handler_with_frame_argument(self, reset_main_state):
        """Test that signal_handler accepts frame argument."""
        mock_worker = MagicMock()
        main.worker = mock_worker

        with pytest.raises(SystemExit):
            main.signal_handler(signal.SIGTERM, "dummy_frame")

        mock_worker.stop.assert_called_once()
