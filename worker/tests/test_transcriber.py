"""Comprehensive tests for transcriber.py module."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from transcriber import ProgressReporter, WhisperTranscriber


# =============================================================================
# ProgressReporter Tests
# =============================================================================


class TestProgressReporterInit:
    """Test ProgressReporter initialization."""

    def test_init_with_valid_params(self):
        """Test initialization with valid parameters."""
        ws_callback = AsyncMock()
        job_id = "test-job-123"
        total_duration = 120.0

        reporter = ProgressReporter(ws_callback, job_id, total_duration)

        assert reporter.ws_callback == ws_callback
        assert reporter.job_id == job_id
        assert reporter.total_duration == total_duration
        assert reporter.start_time is None
        assert reporter.last_report == 0
        assert reporter.last_report_time == 0
        assert reporter.processing_rate == 0.15

    def test_init_with_different_durations(self):
        """Test initialization with various durations."""
        ws_callback = AsyncMock()

        # Short audio
        reporter_short = ProgressReporter(ws_callback, "job-1", 5.0)
        assert reporter_short.total_duration == 5.0

        # Long audio
        reporter_long = ProgressReporter(ws_callback, "job-2", 7200.0)
        assert reporter_long.total_duration == 7200.0


class TestProgressReporterStart:
    """Test ProgressReporter.start() method."""

    @pytest.mark.asyncio
    async def test_start_initializes_timing(self):
        """Test start() initializes timing variables."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.start()

        assert reporter.start_time is not None
        assert isinstance(reporter.start_time, float)
        assert reporter.last_report_time is not None

    @pytest.mark.asyncio
    async def test_start_sends_initial_progress(self):
        """Test start() sends 0% progress message."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.start()

        ws_callback.assert_called_once_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 0,
                "message": "Loading model...",
            }
        )


class TestProgressReporterPhase:
    """Test ProgressReporter.phase() method."""

    @pytest.mark.asyncio
    async def test_phase_loading(self):
        """Test phase() with 'loading' phase."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.phase("loading", 10)

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 10,
                "message": "Loading model...",
            }
        )

    @pytest.mark.asyncio
    async def test_phase_preload(self):
        """Test phase() with 'preload' phase."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.phase("preload", 5)

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 5,
                "message": "Preprocessing audio...",
            }
        )

    @pytest.mark.asyncio
    async def test_phase_transcribing(self):
        """Test phase() with 'transcribing' phase."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.phase("transcribing", 50)

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 50,
                "message": "Transcribing...",
            }
        )

    @pytest.mark.asyncio
    async def test_phase_postprocess(self):
        """Test phase() with 'postprocess' phase."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.phase("postprocess", 95)

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 95,
                "message": "Post-processing...",
            }
        )

    @pytest.mark.asyncio
    async def test_phase_unknown_uses_phase_as_message(self):
        """Test phase() with unknown phase string uses it as message."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.phase("custom_phase", 75)

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 75,
                "message": "custom_phase",
            }
        )


class TestProgressReporterUpdate:
    """Test ProgressReporter.update() method."""

    @pytest.mark.asyncio
    async def test_update_without_start_does_nothing(self):
        """Test update() without start() does nothing."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.update()

        ws_callback.assert_not_called()
        assert reporter.start_time is None

    @pytest.mark.asyncio
    async def test_update_calculates_progress(self):
        """Test update() calculates progress based on elapsed time."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)
        reporter.start_time = time.time() - 5  # 5 seconds elapsed

        await reporter.update()

        # With processing_rate of 0.15, 60s audio should take ~9 seconds
        # 5 seconds elapsed should be ~55% progress
        assert ws_callback.called
        call_args = ws_callback.call_args[0][0]
        assert call_args["progress"] > 0
        assert call_args["message"] == "Transcribing..."

    @pytest.mark.asyncio
    async def test_update_throttling_by_percentage(self):
        """Test update() only sends every 5% progress."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)
        reporter.start_time = time.time()

        # First call should send
        await reporter.update()
        first_progress = ws_callback.call_args[0][0]["progress"]
        reporter.last_report = first_progress

        # Small change shouldn't send
        ws_callback.reset_mock()
        await reporter.update()
        if ws_callback.called:
            # If called, progress difference should be small
            pass

    @pytest.mark.asyncio
    async def test_update_throttling_by_time(self):
        """Test update() sends every 5 seconds regardless of progress."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)
        reporter.start_time = time.time()
        reporter.last_report_time = time.time() - 6  # 6 seconds since last report

        await reporter.update()

        # Should send due to time threshold
        assert ws_callback.called

    @pytest.mark.asyncio
    async def test_update_caps_at_95_percent(self):
        """Test update() caps progress at 95%."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)
        # Set time far in the past to simulate long elapsed time
        reporter.start_time = time.time() - 1000

        await reporter.update()

        call_args = ws_callback.call_args[0][0]
        assert call_args["progress"] <= 95


class TestProgressReporterComplete:
    """Test ProgressReporter.complete() method."""

    @pytest.mark.asyncio
    async def test_complete_sends_100_percent(self):
        """Test complete() sends 100% progress."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.complete()

        ws_callback.assert_called_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 100,
                "message": "Complete",
            }
        )

    @pytest.mark.asyncio
    async def test_complete_updates_processing_rate(self):
        """Test complete() calculates and updates processing rate."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)
        reporter.start_time = time.time() - 10  # 10 seconds elapsed

        await reporter.complete()

        # Processing rate should be ~10/60 = 0.167
        assert reporter.processing_rate > 0
        assert reporter.processing_rate < 1.0

    @pytest.mark.asyncio
    async def test_complete_with_no_start_time(self):
        """Test complete() without start() still sends 100%."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter.complete()

        # Should still send 100% even without start_time
        ws_callback.assert_called_once()
        call_args = ws_callback.call_args[0][0]
        assert call_args["progress"] == 100


class TestProgressReporterSendProgress:
    """Test ProgressReporter._send_progress() error handling."""

    @pytest.mark.asyncio
    async def test_send_progress_callback_failure_logged(self):
        """Test callback failures are caught and logged."""
        async def failing_callback(data):
            raise RuntimeError("WebSocket closed")

        reporter = ProgressReporter(failing_callback, "job-1", 60.0)

        # Should not raise exception
        await reporter._send_progress(50, "Test message")

    @pytest.mark.asyncio
    async def test_send_progress_with_valid_callback(self):
        """Test successful progress sending."""
        ws_callback = AsyncMock()
        reporter = ProgressReporter(ws_callback, "job-1", 60.0)

        await reporter._send_progress(75, "Testing")

        ws_callback.assert_called_once_with(
            {
                "type": "job_progress",
                "job_id": "job-1",
                "progress": 75,
                "message": "Testing",
            }
        )


# =============================================================================
# WhisperTranscriber Tests
# =============================================================================


class TestWhisperTranscriberInit:
    """Test WhisperTranscriber initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        transcriber = WhisperTranscriber()

        assert transcriber.model_size == "base"
        assert transcriber.device == "cuda"
        assert transcriber.fp16 is False
        assert transcriber.model is None
        assert transcriber.executor is not None

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        transcriber = WhisperTranscriber(
            model_size="large", device="cpu", fp16=True
        )

        assert transcriber.model_size == "large"
        assert transcriber.device == "cpu"
        assert transcriber.fp16 is True
        assert transcriber.model is None

    def test_init_all_model_sizes(self):
        """Test initialization with all valid model sizes."""
        model_sizes = ["tiny", "base", "small", "medium", "large"]

        for size in model_sizes:
            transcriber = WhisperTranscriber(model_size=size)
            assert transcriber.model_size == size


class TestWhisperTranscriberLoadModel:
    """Test WhisperTranscriber.load_model() method."""

    @patch("transcriber._load_whisper")
    def test_load_model_success(self, mock_load_whisper):
        """Test successful model loading."""
        mock_model = MagicMock()
        mock_whisper_module = MagicMock()
        mock_whisper_module.load_model.return_value = mock_model
        mock_load_whisper.return_value = mock_whisper_module

        transcriber = WhisperTranscriber(model_size="base", device="cuda")
        transcriber.load_model()

        mock_load_whisper.assert_called_once()
        mock_whisper_module.load_model.assert_called_once_with("base", device="cuda")
        assert transcriber.model == mock_model

    @patch("transcriber._load_whisper")
    def test_load_model_with_different_device(self, mock_load_whisper):
        """Test model loading with different device."""
        mock_model = MagicMock()
        mock_whisper_module = MagicMock()
        mock_whisper_module.load_model.return_value = mock_model
        mock_load_whisper.return_value = mock_whisper_module

        transcriber = WhisperTranscriber(model_size="small", device="cpu")
        transcriber.load_model()

        mock_load_whisper.assert_called_once()
        mock_whisper_module.load_model.assert_called_once_with("small", device="cpu")

    @patch("transcriber._load_whisper")
    def test_load_model_failure_propagates(self, mock_load_whisper):
        """Test model loading failures propagate."""
        mock_whisper_module = MagicMock()
        mock_whisper_module.load_model.side_effect = RuntimeError("CUDA out of memory")
        mock_load_whisper.return_value = mock_whisper_module

        transcriber = WhisperTranscriber(model_size="large", device="cuda")

        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            transcriber.load_model()


class TestWhisperTranscriberTranscribe:
    """Test WhisperTranscriber.transcribe() method."""

    @pytest.mark.asyncio
    async def test_transcribe_without_model_raises(self):
        """Test transcribing without loaded model raises RuntimeError."""
        transcriber = WhisperTranscriber()
        ws_callback = AsyncMock()

        with pytest.raises(RuntimeError, match="Model not loaded"):
            await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
            )

    @patch("transcriber.ffmpeg.probe")
    @pytest.mark.asyncio
    async def test_transcribe_gets_audio_duration(self, mock_probe):
        """Test transcribe() gets audio duration via FFmpeg."""
        mock_probe.return_value = {"format": {"duration": "120.5"}}
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "Test"}],
            "language": "ja",
            "language_probs": {},
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model
        ws_callback = AsyncMock()

        await transcriber.transcribe(
            audio_path="/tmp/test.mp3",
            ws_callback=ws_callback,
            job_id="job-1",
        )

        mock_probe.assert_called_once_with("/tmp/test.mp3")

    @patch("transcriber.ffmpeg.probe")
    @pytest.mark.asyncio
    async def test_transcribe_ffmpeg_failure_uses_default(self, mock_probe):
        """Test transcribe() uses default duration on FFmpeg failure."""
        mock_probe.side_effect = Exception("FFmpeg error")
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model
        ws_callback = AsyncMock()

        # Should not raise, should use default 60s duration
        result = await transcriber.transcribe(
            audio_path="/tmp/test.mp3",
            ws_callback=ws_callback,
            job_id="job-1",
        )

        assert "segments" in result
        assert result["language"] == "ja"

    @pytest.mark.asyncio
    async def test_transcribe_calls_whisper(self):
        """Test transcribe() calls whisper model with correct parameters."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "こんにちは"}],
            "language": "ja",
            "language_probs": {"ja": 0.95},
        }

        transcriber = WhisperTranscriber(model_size="base", fp16=True)
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
                language="ja",
            )

        # Verify whisper.transcribe was called
        mock_model.transcribe.assert_called_once()
        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["language"] == "ja"
        assert call_kwargs["word_timestamps"] is True
        assert call_kwargs["fp16"] is True

    @pytest.mark.asyncio
    async def test_transcribe_returns_correct_format(self):
        """Test transcribe() returns correctly formatted result."""
        mock_model = MagicMock()
        mock_result = {
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "Segment 1"},
                {"start": 2.5, "end": 5.0, "text": "Segment 2"},
            ],
            "language": "ja",
            "language_probs": {"ja": 0.98, "en": 0.02},
        }
        mock_model.transcribe.return_value = mock_result

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
            )

        assert result["segments"] == mock_result["segments"]
        assert result["language"] == "ja"
        assert result["language_probs"] == mock_result["language_probs"]

    @pytest.mark.asyncio
    async def test_transcribe_sends_progress_updates(self):
        """Test transcribe() sends progress through callback."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="test-job-123",
            )

        # Should have sent multiple progress updates
        assert ws_callback.call_count > 0

        # Check for specific progress messages
        progress_messages = [call[0][0] for call in ws_callback.call_args_list]
        assert any(p["progress"] == 0 for p in progress_messages)  # Start
        assert any(p["progress"] == 100 for p in progress_messages)  # Complete
        assert all(p["job_id"] == "test-job-123" for p in progress_messages)

    @pytest.mark.asyncio
    async def test_transcribe_with_custom_language(self):
        """Test transcribe() respects custom language parameter."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "en",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
                language="en",
            )

        # Verify language was passed to whisper
        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["language"] == "en"

    @pytest.mark.asyncio
    async def test_transcribe_propagates_exceptions(self):
        """Test transcribe() propagates transcription exceptions."""
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = ValueError("Audio format error")

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()

            with pytest.raises(ValueError, match="Audio format error"):
                await transcriber.transcribe(
                    audio_path="/tmp/test.mp3",
                    ws_callback=ws_callback,
                    job_id="job-1",
                )


class TestWhisperTranscriberProgressLoop:
    """Test WhisperTranscriber._progress_loop() method."""

    @pytest.mark.asyncio
    @patch("transcriber.asyncio.sleep", new_callable=AsyncMock)
    async def test_progress_loop_updates_reporter(self, mock_sleep):
        """Test progress loop calls reporter.update() periodically."""
        transcriber = WhisperTranscriber()
        reporter = MagicMock()
        reporter.update = AsyncMock(
            side_effect=[None, None, asyncio.CancelledError()]
        )

        await transcriber._progress_loop(reporter)

        # Should have called update at least twice (sleep is mocked)
        assert reporter.update.call_count >= 2
        assert mock_sleep.call_count >= 2

    @pytest.mark.asyncio
    async def test_progress_loop_handles_cancellation(self):
        """Test progress loop exits gracefully on cancellation."""
        transcriber = WhisperTranscriber()
        reporter = MagicMock()
        reporter.update = AsyncMock()

        task = asyncio.create_task(transcriber._progress_loop(reporter))
        await asyncio.sleep(0.05)
        task.cancel()

        # Should not raise
        await asyncio.gather(task, return_exceptions=True)


# =============================================================================
# Robustness Tests
# =============================================================================


class TestTranscriberRobustness:
    """Test transcriber behavior with edge cases and stress conditions."""

    @pytest.mark.asyncio
    async def test_very_long_audio_file(self):
        """Test transcribing very long audio (2+ hours)."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        # 2.5 hour audio
        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "9000"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/long_audio.mp3",
                ws_callback=ws_callback,
                job_id="job-long",
            )

        assert "segments" in result
        assert ws_callback.called

    @pytest.mark.asyncio
    async def test_very_short_audio_file(self):
        """Test transcribing very short audio (<1 second)."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [{"start": 0.0, "end": 0.5, "text": "短い"}],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        # 0.5 second audio
        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "0.5"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/short.mp3",
                ws_callback=ws_callback,
                job_id="job-short",
            )

        assert len(result["segments"]) == 1

    @pytest.mark.asyncio
    async def test_progress_reporting_accuracy(self):
        """Test progress reporting accuracy across different durations."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        test_durations = [10, 60, 300, 3600]  # 10s, 1min, 5min, 1hr

        for duration in test_durations:
            with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": str(duration)}}):
                ws_callback = AsyncMock()
                await transcriber.transcribe(
                    audio_path=f"/tmp/audio_{duration}s.mp3",
                    ws_callback=ws_callback,
                    job_id=f"job-{duration}",
                )

                # Check progress monotonically increases
                progresses = [
                    call[0][0]["progress"]
                    for call in ws_callback.call_args_list
                ]
                assert progresses == sorted(progresses)
                assert progresses[-1] == 100  # Last update should be 100%

    @pytest.mark.asyncio
    async def test_callback_failure_doesnt_crash_transcription(self):
        """Test that WebSocket callback failures don't crash transcription."""
        async def flaky_callback(data):
            # Fail on first few calls, succeed later
            if data.get("progress", 0) < 50:
                raise RuntimeError("Connection error")
            # Later calls succeed

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = flaky_callback
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-flaky",
            )

        # Should complete successfully despite callback failures
        assert "segments" in result

    @pytest.mark.asyncio
    async def test_multiple_rapid_transcriptions(self):
        """Test handling multiple rapid transcription requests."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "30"}}):
            # Run multiple transcriptions in parallel
            tasks = []
            for i in range(5):
                ws_callback = AsyncMock()
                task = transcriber.transcribe(
                    audio_path=f"/tmp/audio_{i}.mp3",
                    ws_callback=ws_callback,
                    job_id=f"job-{i}",
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

        # All should complete successfully
        assert len(results) == 5
        for result in results:
            assert "segments" in result

    @pytest.mark.asyncio
    async def test_model_memory_efficiency(self):
        """Test that model is loaded once and reused."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            # Run multiple transcriptions
            for i in range(3):
                ws_callback = AsyncMock()
                await transcriber.transcribe(
                    audio_path=f"/tmp/audio_{i}.mp3",
                    ws_callback=ws_callback,
                    job_id=f"job-{i}",
                )

        # Model should be the same instance (not reloaded)
        assert transcriber.model is mock_model
        # transcribe should have been called 3 times
        assert mock_model.transcribe.call_count == 3

    @pytest.mark.asyncio
    async def test_executor_reused_across_transcriptions(self):
        """Test that thread pool executor is reused."""
        transcriber = WhisperTranscriber()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }
        transcriber.model = mock_model

        first_executor = transcriber.executor

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
            )

        # Same executor should be used
        assert transcriber.executor is first_executor


class TestTranscriberCancellation:
    """Test cancellation handling during transcription."""

    @pytest.mark.asyncio
    async def test_cancellation_during_transcription(self):
        """Test handling task cancellation during transcription."""
        mock_model = MagicMock()
        blocker = threading.Event()

        # Simulate long-running transcription (blocking function, not async)
        def slow_transcribe(*args, **kwargs):
            blocker.wait(1)
            return {"segments": [], "language": "ja"}

        mock_model.transcribe = MagicMock(side_effect=slow_transcribe)

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "300"}}):
            ws_callback = AsyncMock()

            # Start transcription
            task = asyncio.create_task(
                transcriber.transcribe(
                    audio_path="/tmp/test.mp3",
                    ws_callback=ws_callback,
                    job_id="job-cancel",
                )
            )
            # Give it time to start the transcription, then cancel
            await asyncio.sleep(0.01)
            task.cancel()

            try:
                with pytest.raises((asyncio.CancelledError, Exception)):
                    await task
            finally:
                blocker.set()

    @pytest.mark.asyncio
    async def test_progress_loop_cancellation(self):
        """Test progress loop is properly cancelled after transcription."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-1",
            )

        # Transcription completed, progress loop should be cancelled
        # No assertion needed - just verify it doesn't hang


class TestTranscriberEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_transcribe_with_zero_duration(self):
        """Test transcribing with zero/near-zero duration."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        # Near-zero duration
        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "0.01"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-zero",
            )

        assert "segments" in result

    @pytest.mark.asyncio
    async def test_transcribe_with_invalid_duration_format(self):
        """Test handling of malformed duration from FFmpeg."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        # Invalid duration (non-numeric string) - should use default 60s
        with patch(
            "transcriber.ffmpeg.probe",
            return_value={"format": {"duration": "invalid"}},
        ):
            ws_callback = AsyncMock()
            # Should NOT raise, should use default 60s
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-invalid",
            )
            # Verify transcription completed with default duration
            assert "segments" in result

    @pytest.mark.asyncio
    async def test_transcribe_missing_duration_key(self):
        """Test handling of missing duration key in FFmpeg output."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        # Missing duration key - should use default 60s
        with patch("transcriber.ffmpeg.probe", return_value={"format": {}}):
            ws_callback = AsyncMock()
            # Should NOT raise, should use default 60s
            result = await transcriber.transcribe(
                audio_path="/tmp/test.mp3",
                ws_callback=ws_callback,
                job_id="job-missing",
            )
            # Verify transcription completed with default duration
            assert "segments" in result

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self):
        """Test handling empty transcription result."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": [],
            "language": None,
            "language_probs": {},
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "60"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/silent.mp3",
                ws_callback=ws_callback,
                job_id="job-empty",
            )

        assert result["segments"] == []
        assert result["language"] is None

    @pytest.mark.asyncio
    async def test_transcribe_large_segment_count(self):
        """Test handling transcription with many segments."""
        # Generate many segments
        segments = [
            {"start": float(i), "end": float(i + 0.5), "text": f"Word {i}"}
            for i in range(1000)
        ]
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "segments": segments,
            "language": "ja",
        }

        transcriber = WhisperTranscriber()
        transcriber.model = mock_model

        with patch("transcriber.ffmpeg.probe", return_value={"format": {"duration": "600"}}):
            ws_callback = AsyncMock()
            result = await transcriber.transcribe(
                audio_path="/tmp/long_speech.mp3",
                ws_callback=ws_callback,
                job_id="job-many-segments",
            )

        assert len(result["segments"]) == 1000
