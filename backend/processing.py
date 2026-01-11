from __future__ import annotations

import asyncio
import difflib
import os
import re
import time
from functools import partial
from typing import Dict, List, Optional

import services_registry as services
import state
from models import ProcessingMetrics, Segment, TaskStatus, VideoResponse, Word
from uploads import release_upload_session
from utils.logger import get_logger

logger = get_logger(__name__)


def update_task(
    task_id: str,
    status: TaskStatus,
    progress: int = 0,
    message: str = "",
    result=None,
    error: str = None,
):
    state.update_task(task_id, status, progress, message, result=result, error=error)


def _ensure_services_initialized():
    if not all(
        [
            services.downloader,
            services.transcriber,
            services.analyzer,
            services.aligner,
            services.translator,
            services.subtitle_linearizer,
        ]
    ):
        raise RuntimeError(
            "Services not initialized. Call services_registry.init_services() at startup."
        )


async def run_cpu_bound(func, *args, **kwargs):
    """Run CPU-bound function in thread pool executor."""
    if state.executor is None:
        logger.warning("ThreadPoolExecutor not initialized; falling back to asyncio.to_thread")
        return await asyncio.to_thread(func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(state.executor, partial(func, *args, **kwargs))


def check_subtitle_similarity(
    generated_segments: List[Dict],
    reference_segments: List[Dict],
    threshold: float = 0.1,
) -> List[str]:
    """
    Check similarity between generated segments and reference segments.
    Returns a list of warnings if similarity is low.
    """
    if not generated_segments or not reference_segments:
        return []

    # Helper to extract text from a list of segments
    def extract_text(segments, sample_ratio=0.2, max_chars=2000):
        total_len = len(segments)
        if total_len == 0:
            return ""

        # Define ranges: Start, Middle, End
        count = max(1, int(total_len * sample_ratio))

        ranges = [
            (0, count),  # Start
            (total_len // 2 - count // 2, total_len // 2 + count // 2),  # Middle
            (total_len - count, total_len),  # End
        ]

        text_parts = []
        for start, end in ranges:
            start = max(0, start)
            end = min(total_len, end)
            if start >= end:
                continue

            chunk_text = "".join([seg.get("text", "") for seg in segments[start:end]])
            text_parts.append(chunk_text)

        full_text = "".join(text_parts)
        # Normalize: Remove whitespace and common punctuation
        normalized = re.sub(r"[\s\u3000\u3001\u3002,.!?]", "", full_text).lower()
        return normalized[: max_chars * 3]  # Cap length just in case

    text_gen = extract_text(generated_segments)
    text_ref = extract_text(reference_segments)

    if not text_gen or not text_ref:
        return []

    # Calculate similarity
    ratio = difflib.SequenceMatcher(None, text_gen, text_ref).ratio()
    logger.info(f"Subtitle similarity score: {ratio:.4f}")

    warnings = []
    if ratio < threshold:
        warning_msg = (
            "Low subtitle match detected (Similarity: "
            f"{ratio:.0%}). Please check if you uploaded the correct subtitle file."
        )
        logger.warning(warning_msg)
        warnings.append(warning_msg)

    return warnings


async def process_audio_task(
    task_id: str,
    file_path: str,
    video_id: str,
    title: str,
    download_time: float = 0.0,
    subtitle_path: Optional[str] = None,
):
    """
    Process audio/video file and generate learning segments.

    Args:
        task_id: Unique task identifier
        file_path: Path to the audio/video file
        video_id: Video identifier
        title: Video title
        download_time: Time spent downloading (for metrics)
        subtitle_path: Optional path to user-provided subtitle file (SRT format).
                      If provided, skips AI transcription and uses the subtitle directly.
    """
    start_total = time.time()
    transcribe_time = 0.0
    analysis_time = 0.0
    translation_time = 0.0
    has_word_timestamps = True  # Track if we have precise word-level timestamps
    warnings = []

    try:
        _ensure_services_initialized()
        # 2. Transcribe (Always run AI for timing reference)
        if services.whisper_lock:
            update_task(
                task_id,
                TaskStatus.PROCESSING,
                5,
                f"Waiting for {services.whisper_lock_label} slot...",
            )
            async with services.whisper_lock:
                update_task(
                    task_id,
                    TaskStatus.PROCESSING,
                    10,
                    "Transcribing audio (Generating Timing Reference)...",
                )
                logger.info(f"Task {task_id}: Starting transcription for timing reference")
                t0 = time.time()
                gen_result = await run_cpu_bound(
                    services.transcriber.transcribe,
                    file_path,
                    language="ja",
                )
                generated_segments = gen_result["segments"]
                transcribe_time = time.time() - t0
                logger.info(
                    "Task %s: Transcription completed in %.2fs",
                    task_id,
                    transcribe_time,
                )
        else:
            update_task(
                task_id,
                TaskStatus.PROCESSING,
                10,
                "Transcribing audio (Generating Timing Reference)...",
            )
            logger.info(f"Task {task_id}: Starting transcription for timing reference")
            t0 = time.time()
            gen_result = await run_cpu_bound(
                services.transcriber.transcribe,
                file_path,
                language="ja",
            )
            generated_segments = gen_result["segments"]
            transcribe_time = time.time() - t0
            logger.info(
                "Task %s: Transcription completed in %.2fs",
                task_id,
                transcribe_time,
            )

        reference_segments = []

        # 3. Load & Calibrate User Subtitle (if provided)
        if subtitle_path and os.path.exists(subtitle_path):
            update_task(
                task_id,
                TaskStatus.PROCESSING,
                30,
                "Loading and Calibrating User Subtitle...",
            )
            logger.info(f"Task {task_id}: Loading user-provided subtitle file")

            # Load Reference
            ref_result = await run_cpu_bound(services.transcriber.load_subtitle, subtitle_path)
            raw_reference_segments = ref_result["segments"]
            logger.info(
                "Task %s: Loaded %s segments from user subtitle",
                task_id,
                len(raw_reference_segments),
            )

            # Deduplicate scrolling subtitles with metadata tracking
            logger.info(f"Task {task_id}: Deduplicating scrolling subtitles")
            merged_text, char_metadata = services.subtitle_linearizer.deduplicate_with_metadata(
                raw_reference_segments
            )
            logger.info(
                "Task %s: Merged text length: %s chars",
                task_id,
                len(merged_text),
            )

            # Check Similarity using merged text vs AI text
            logger.info(f"Task {task_id}: Checking subtitle similarity")
            temp_ref_segments = [{"text": merged_text, "start": 0, "end": 0}]
            warnings = check_subtitle_similarity(
                generated_segments,
                temp_ref_segments,
                threshold=services.subtitle_similarity_threshold,
            )
            if warnings:
                logger.warning(f"Task {task_id}: Subtitle check warnings: {warnings}")
            else:
                logger.info(f"Task {task_id}: Subtitle check passed")

            # Calibrate timestamps using new method
            logger.info(f"Task {task_id}: Calibrating timestamps")
            _, char_timestamps = await run_cpu_bound(
                services.aligner.calibrate_from_merged,
                merged_text,
                char_metadata,
                generated_segments,
            )

            # Rebuild segments with calibrated timestamps
            logger.info(f"Task {task_id}: Rebuilding segments")
            reference_segments = services.aligner.rebuild_segments_with_timestamps(
                merged_text,
                char_metadata,
                char_timestamps,
            )
            logger.info(
                "Task %s: Rebuilt %s segments with timestamps",
                task_id,
                len(reference_segments),
            )

            has_word_timestamps = True

        else:
            # No subtitle provided - use AI transcription as reference
            reference_segments = generated_segments
            has_word_timestamps = True

        update_task(task_id, TaskStatus.PROCESSING, 40, "Analyzing Japanese text...")

        # 4. Process Segments (Analyze & Align)
        logger.info(f"Task {task_id}: Analyzing {len(reference_segments)} segments")
        final_segments = []
        raw_texts = []

        # We can also offload the analysis loop if it's heavy, but let's see.
        # For now, let's keep it in the loop but yield control occasionally if needed.
        # However, MeCab analysis IS CPU bound.

        def analyze_segments(segments):
            processed_segments = []
            texts = []
            for seg in segments:
                text = seg["text"].strip()
                if not text:
                    continue
                texts.append(text)
                whisper_words = seg.get("words", [])
                mecab_tokens = services.analyzer.analyze(text)
                aligned_tokens = services.aligner.align(
                    whisper_words,
                    mecab_tokens,
                    segment_start=seg.get("start"),
                    segment_end=seg.get("end"),
                )

                words_model = []
                for token in aligned_tokens:
                    words_model.append(
                        Word(
                            text=token["text"],
                            reading=token.get("reading", ""),
                            start=token.get("start") or 0.0,
                            end=token.get("end") or 0.0,
                        )
                    )

                processed_segments.append(
                    Segment(
                        words=words_model,
                        translation="",
                        start=seg["start"],
                        end=seg["end"],
                    )
                )
            return processed_segments, texts

        # Run analysis in thread
        t0 = time.time()
        final_segments, raw_texts = await run_cpu_bound(analyze_segments, reference_segments)
        analysis_time = time.time() - t0

        update_task(task_id, TaskStatus.PROCESSING, 70, "Translating to Chinese...")

        # 4. Translate
        logger.info(f"Task {task_id}: Translating {len(raw_texts)} segments")
        t0 = time.time()
        # Translation involves network I/O. We updated translator to be async and concurrent.
        translations = await services.translator.translate_batch(raw_texts)
        translation_time = time.time() - t0

        # Map translations back (handle potential length mismatch gracefully)
        for i, trans in enumerate(translations):
            if i < len(final_segments):
                final_segments[i].translation = trans

        logger.info(f"Task {task_id}: Processing complete")

        total_time = (time.time() - start_total) + download_time

        metrics = ProcessingMetrics(
            download_time=download_time,
            transcribe_time=transcribe_time,
            analysis_time=analysis_time,
            translation_time=translation_time,
            total_time=total_time,
        )

        logger.info(
            "Task %s completed - Download: %.2fs, Transcribe: %.2fs, "
            "Analysis: %.2fs, Translation: %.2fs, Total: %.2fs",
            task_id,
            metrics.download_time,
            metrics.transcribe_time,
            metrics.analysis_time,
            metrics.translation_time,
            metrics.total_time,
        )

        final_response = VideoResponse(
            video_id=video_id,
            title=title,
            segments=final_segments,
            metrics=metrics,
            has_word_timestamps=has_word_timestamps,
            warnings=warnings,
        )

        update_task(task_id, TaskStatus.COMPLETED, 100, "Completed", result=final_response)

    except asyncio.CancelledError:
        logger.warning(f"Task {task_id} cancelled")
        update_task(
            task_id,
            TaskStatus.FAILED,
            0,
            "Processing cancelled",
            error="Processing cancelled",
        )
        raise
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        update_task(task_id, TaskStatus.FAILED, 0, "Processing failed", error=str(e))
    finally:
        # Cleanup audio/video file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Cleaned up file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup file {file_path}: {e}")
        # Cleanup subtitle file if provided
        if subtitle_path and os.path.exists(subtitle_path):
            try:
                os.remove(subtitle_path)
                logger.debug(f"Cleaned up subtitle: {subtitle_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup subtitle {subtitle_path}: {e}")
        release_upload_session(task_id)


async def download_and_process(task_id: str, url: str):
    temp_file = None
    try:
        _ensure_services_initialized()
        update_task(task_id, TaskStatus.PROCESSING, 5, "Downloading video...")
        logger.info(f"Task {task_id}: Downloading from URL: {url}")

        t0 = time.time()
        temp_file, info = await asyncio.to_thread(services.downloader.download_audio, url)
        download_time = time.time() - t0

        video_title = info.get("title", "Unknown Video")
        video_id = info.get("id", "unknown_id")
        logger.info(
            "Task %s: Download completed in %.2fs - %s",
            task_id,
            download_time,
            video_title,
        )

        await process_audio_task(
            task_id,
            temp_file,
            video_id,
            video_title,
            download_time=download_time,
        )
    except asyncio.CancelledError:
        logger.warning(f"Task {task_id}: Download cancelled")
        update_task(
            task_id,
            TaskStatus.FAILED,
            0,
            "Download cancelled",
            error="Download cancelled",
        )
        raise
    except Exception as e:
        logger.error(f"Task {task_id}: Download failed - {e}", exc_info=True)
        update_task(task_id, TaskStatus.FAILED, 0, "Download failed", error=str(e))
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.debug(f"Cleaned up file: {temp_file}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup file {temp_file}: {cleanup_error}")
