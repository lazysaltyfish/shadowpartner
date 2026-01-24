"""Subtitle parsing and Whisper text cleanup helpers."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from utils.logger import get_logger

logger = get_logger(__name__)


def clean_whisper_text(text: str) -> str:
    """
    Remove bracket annotations from Whisper output.

    Whisper inserts bracket-annotated non-speech events in the transcription,
    such as [applause], [laughter], [music]. These are not useful for
    shadow reading practice and should be removed.
    """
    if not text:
        return text

    # Iterate until no more brackets are found
    while True:
        cleaned = re.sub(r"\[.*?\]", "", text)
        cleaned = re.sub(r"【.*?】", "", cleaned)
        cleaned = re.sub(r"［.*?］", "", cleaned)

        if cleaned == text:
            break
        text = cleaned

    return re.sub(r"\s+", " ", text).strip()


def clean_segments(result: Dict[str, Any]) -> None:
    """Clean Whisper segments in-place to remove bracket annotations."""
    segments = result.get("segments", [])
    if not segments:
        return

    cleaned_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue

        original_text = segment.get("text", "")
        cleaned_text = clean_whisper_text(original_text)
        if not cleaned_text:
            continue

        cleaned_words = []
        for word in segment.get("words", []):
            if isinstance(word, dict):
                cleaned_word_text = clean_whisper_text(word.get("word", ""))
                if cleaned_word_text:
                    word["word"] = cleaned_word_text
                    cleaned_words.append(word)
            elif hasattr(word, "word"):
                cleaned_word_text = clean_whisper_text(getattr(word, "word", ""))
                if cleaned_word_text:
                    setattr(word, "word", cleaned_word_text)
                    cleaned_words.append(word)

        segment["text"] = cleaned_text
        if cleaned_words:
            segment["words"] = cleaned_words

        cleaned_segments.append(segment)

    result["segments"] = cleaned_segments


def parse_srt_time(time_str: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_srt(content: str) -> List[dict]:
    """Parse SRT subtitle content and return segments in Standard Segment format."""
    segments: List[dict] = []
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        timestamp_idx = -1
        for i, line in enumerate(lines):
            if " --> " in line:
                timestamp_idx = i
                break
        if timestamp_idx == -1:
            continue

        timestamp_line = lines[timestamp_idx]
        text_lines = lines[timestamp_idx + 1 :]

        match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            timestamp_line,
        )
        if not match:
            continue

        start_time = parse_srt_time(match.group(1))
        end_time = parse_srt_time(match.group(2))
        text = " ".join(text_lines).strip()
        if not text:
            continue

        segments.append(
            {
                "text": text,
                "start": start_time,
                "end": end_time,
                "words": [],
            }
        )

    return segments


def load_subtitle(subtitle_path: str | None = None, subtitle_content: str | None = None) -> dict:
    """Load subtitle from file or content string and return in Standard Segment format."""
    if subtitle_content is None and subtitle_path is None:
        raise ValueError("Either subtitle_path or subtitle_content must be provided.")

    if subtitle_content is None:
        assert subtitle_path is not None
        if not os.path.exists(subtitle_path):
            raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "shift_jis", "latin-1"]
        content = None
        for encoding in encodings:
            try:
                with open(subtitle_path, "r", encoding=encoding) as handle:
                    content = handle.read()
                logger.debug(f"Successfully decoded subtitle with encoding: {encoding}")
                break
            except UnicodeDecodeError:
                logger.debug(f"Failed to decode with encoding: {encoding}")
                continue

        if content is None:
            logger.error(
                "Could not decode subtitle file with any supported encoding: %s",
                subtitle_path,
            )
            raise ValueError(
                f"Could not decode subtitle file with any supported encoding: {subtitle_path}"
            )

        subtitle_content = content

    assert subtitle_content is not None

    segments = parse_srt(subtitle_content)
    if not segments:
        logger.error("No valid subtitle segments found in the provided content")
        raise ValueError("No valid subtitle segments found in the provided content.")

    logger.info("Loaded %s subtitle segments from user-provided file", len(segments))
    return {"segments": segments}
