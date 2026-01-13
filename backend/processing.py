from __future__ import annotations

import asyncio
import difflib
import os
import re
import time
import uuid
from collections import Counter
from functools import partial
from typing import Dict, List, Optional

import services_registry as services
import state
from db import get_session
from db.crud import get_asset_by_identifier, get_cached_result
from db.models import Asset, AssetType, SubtitleSource, SubtitleTrack, SubtitleTrackType
from models import ProcessingMetrics, Segment, TaskStatus, VideoResponse, Word
from services.video_utils import get_video_source
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
            services.storage,
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


def is_translation_failure(text: str) -> bool:
    markers = (
        "[翻译错误",
        "[翻译超时",
        "[翻译缺失",
        "[需要配置 GEMINI_API_KEY]",
        "[翻译失败",
    )
    return any(marker in text for marker in markers)


def get_translation_failure_reason(text: str) -> str:
    if "[需要配置 GEMINI_API_KEY]" in text:
        return "missing_api_key"
    if "[翻译超时" in text:
        return "timeout"
    if "[翻译错误" in text:
        return "error"
    if "[翻译缺失" in text:
        return "missing"
    if "[翻译失败" in text:
        return "failed"
    return "unknown"


def _truncate(text: str, max_len: int = 120) -> str:
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


def check_cache(asset_identifier: str) -> Optional[VideoResponse]:
    """Check database for cached processing result.

    Args:
        asset_identifier: Asset identifier (YouTube ID or file hash)

    Returns:
        VideoResponse if cache hit, None otherwise
    """
    with get_session() as db:
        cached_content = get_cached_result(db, asset_identifier)
        if not cached_content:
            return None

        logger.info(f"Cache hit for asset: {asset_identifier}")

        segments_data = cached_content.get("segments", [])
        segments = []
        for seg_dict in segments_data:
            words = [Word(**w) for w in seg_dict.get("words", [])]
            segments.append(
                Segment(
                    words=words,
                    translation=seg_dict.get("translation", ""),
                    start=seg_dict.get("start", 0.0),
                    end=seg_dict.get("end", 0.0),
                )
            )

        metrics_dict = cached_content.get("metrics")
        metrics = ProcessingMetrics(**metrics_dict) if metrics_dict else None

        return VideoResponse(
            video_id=asset_identifier,
            title=cached_content.get("title", ""),
            segments=segments,
            metrics=metrics,
            has_word_timestamps=cached_content.get("has_word_timestamps", True),
            warnings=cached_content.get("warnings", []),
        )


def save_subtitle_to_db(
    asset_identifier: str,
    video_response: VideoResponse,
    source: SubtitleSource,
    asset_type: Optional[AssetType] = None,
    storage_path: Optional[str] = None,
    meta: Optional[dict] = None,
    created_by: Optional[uuid.UUID] = None,
):
    """Save processed subtitle to database.

    Args:
        asset_identifier: Asset identifier (YouTube ID or file hash)
        video_response: Processed video response with segments
        source: Source type (AI_GENERATED or USER_UPLOAD)
        asset_type: Asset type (UPLOAD or YOUTUBE)
        storage_path: Storage path for uploaded files
        meta: Optional asset metadata
        created_by: User ID who created the asset
    """
    with get_session() as db:
        if asset_type is None:
            asset_type = (
                AssetType.UPLOAD
                if get_video_source(asset_identifier) == "upload"
                else AssetType.YOUTUBE
            )

        asset = get_asset_by_identifier(db, asset_type, asset_identifier)

        if not asset:
            asset = Asset(
                type=asset_type,
                identifier=asset_identifier,
                storage_path=storage_path,
                meta=meta,
                created_by=created_by,
            )
            db.add(asset)
        else:
            updated = False
            if storage_path and asset.storage_path != storage_path:
                asset.storage_path = storage_path
                updated = True
            if meta:
                asset.meta = {**(asset.meta or {}), **meta}
                updated = True
            if created_by and not asset.created_by:
                asset.created_by = created_by
                updated = True
            if updated:
                db.add(asset)

        segments_data = []
        for seg in video_response.segments:
            segments_data.append(
                {
                    "words": [w.model_dump() for w in seg.words],
                    "translation": seg.translation,
                    "start": seg.start,
                    "end": seg.end,
                }
            )

        content = {
            "title": video_response.title,
            "segments": segments_data,
            "metrics": video_response.metrics.model_dump() if video_response.metrics else None,
            "has_word_timestamps": video_response.has_word_timestamps,
            "warnings": video_response.warnings,
        }

        track = SubtitleTrack(
            asset_id=asset.id,
            track_type=SubtitleTrackType.PROCESSED,
            source=source,
            language="ja",
            content=content,
            is_default=True,
        )
        db.add(track)
        db.commit()
        db.refresh(track)

        logger.info(f"Saved subtitle track to DB for asset_id: {asset.id}")


async def process_audio_task(
    task_id: str,
    file_path: str,
    video_id: str,
    title: str,
    download_time: float = 0.0,
    subtitle_path: Optional[str] = None,
    created_by: Optional[uuid.UUID] = None,
    asset_meta: Optional[dict] = None,
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

        failed_indices = [i for i, text in enumerate(translations) if is_translation_failure(text)]
        failed_count = len(failed_indices)
        if failed_count:
            reason_counts = Counter(
                get_translation_failure_reason(translations[i]) for i in failed_indices
            )
            sample_details = []
            for i in failed_indices[:5]:
                sample_details.append(
                    f"idx={i} reason={get_translation_failure_reason(translations[i])} "
                    f"jp='{_truncate(raw_texts[i])}' zh='{_truncate(translations[i])}'"
                )
            logger.error(
                "Task %s: Translation failed for %s/%s segments; reasons=%s; samples=%s",
                task_id,
                failed_count,
                len(translations),
                dict(reason_counts),
                " | ".join(sample_details),
            )
            raise RuntimeError(
                "Translation failed; skipping persistence "
                f"({failed_count}/{len(translations)}). "
                f"Reasons: {dict(reason_counts)}. See logs for samples."
            )

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

        source = SubtitleSource.USER_UPLOAD if subtitle_path else SubtitleSource.AI_GENERATED
        asset_type = (
            AssetType.UPLOAD if get_video_source(video_id) == "upload" else AssetType.YOUTUBE
        )
        storage_path = None
        storage = services.storage

        if asset_type == AssetType.UPLOAD:
            if storage is None:
                raise RuntimeError("Storage service not initialized")
            if not file_path or not os.path.exists(file_path):
                raise RuntimeError("Upload file missing; cannot persist result")
            try:
                with open(file_path, "rb") as f:
                    storage_path = await storage.save(f, video_id)
                    logger.info(f"Task {task_id}: Saved file to storage: {storage_path}")
            except Exception as e:
                raise RuntimeError("Failed to save upload to storage") from e

        try:
            save_subtitle_to_db(
                video_id,
                final_response,
                source,
                asset_type=asset_type,
                storage_path=storage_path,
                meta=asset_meta,
                created_by=created_by,
            )
        except Exception:
            if storage_path and storage is not None:
                try:
                    await storage.delete(storage_path)
                except Exception as cleanup_error:
                    logger.warning(
                        "Task %s: Failed to cleanup stored file %s: %s",
                        task_id,
                        storage_path,
                        cleanup_error,
                    )
            raise

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
