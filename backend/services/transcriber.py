import os
import re
from typing import Any, Dict, Optional, Tuple, cast

import torch
import whisper

from settings import get_settings
from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

# Setup logger
logger = get_logger(__name__)

# Setup local bin path
setup_local_bin_path()


def clean_whisper_text(text: str) -> str:
    """
    Remove bracket annotations from Whisper output.

    Whisper inserts bracket-annotated non-speech events in the transcription,
    such as [applause], [laughter], [music]. These are not useful for
    shadow reading practice and should be removed.

    Args:
        text: Original Whisper text

    Returns:
        Cleaned text with all [...] and 【...】 content removed

    Examples:
        - "こんにちは[音楽]世界" → "こんにちは世界"
        - "今日[拍手]は" → "今日 は"
        - "Hello[laughter]World" → "Hello World"
        - "正常テキスト" → "正常テキスト"
    """
    if not text:
        return text

    # Iterate until no more brackets are found
    # Handle cases where brackets might appear multiple times
    while True:
        # Remove [...] and 【...】 and full-width ［...］ content
        # Use non-greedy matching *? to handle each bracket pair separately
        cleaned = re.sub(r"\[.*?\]", "", text)
        cleaned = re.sub(r"【.*?】", "", cleaned)
        cleaned = re.sub(r"［.*?］", "", cleaned)

        # If no changes, cleaning is complete
        if cleaned == text:
            break
        text = cleaned

    # Clean up extra spaces (may exist around removed brackets)
    cleaned = re.sub(r"\s+", " ", text).strip()

    return cleaned


def parse_srt_time(time_str: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    # Handle both comma and period as decimal separator
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_srt(content: str) -> list:
    """
    Parse SRT subtitle content and return segments in Standard Segment format.

    Returns:
        list: List of segment dicts with 'text', 'start', 'end', and 'words' keys.
    """
    segments = []
    # Split by double newline to get subtitle blocks
    # Handle different line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # First line is the index (skip it)
        # Second line is the timestamp
        # Remaining lines are the text

        # Find the timestamp line (contains ' --> ')
        timestamp_idx = -1
        for i, line in enumerate(lines):
            if " --> " in line:
                timestamp_idx = i
                break

        if timestamp_idx == -1:
            continue

        timestamp_line = lines[timestamp_idx]
        text_lines = lines[timestamp_idx + 1 :]

        # Parse timestamp: "00:00:01,000 --> 00:00:04,000"
        match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", timestamp_line
        )
        if not match:
            continue

        start_time = parse_srt_time(match.group(1))
        end_time = parse_srt_time(match.group(2))
        text = " ".join(text_lines).strip()

        if not text:
            continue

        # Create segment in Standard Segment format
        # Note: We don't have word-level timestamps from SRT, so words list will be empty
        # The aligner will handle this case via calibration
        segment = {
            "text": text,
            "start": start_time,
            "end": end_time,
            "words": [],  # No word-level timestamps available from SRT
        }
        segments.append(segment)

    return segments


class AudioTranscriber:
    def __init__(self, model_size="base", device=None, fp16=False):
        """
        Initialize the transcriber model.

        Args:
            model_size (str): Size of the whisper model (tiny, base, small, medium, large)
            device (str): Device to run the model on ("cpu" or "cuda").
                         If None, detects automatically.
            fp16 (bool): Whether to use fp16 for inference.
                         WARNING: fp16=True can cause NaN errors on some GPUs,
                         so default is False for stability.
        """
        self.model_size = model_size
        self.fp16 = fp16

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info(
            f"Loading Whisper model ({self.model_size}) on {self.device} with fp16={self.fp16}"
        )
        try:
            self.model = whisper.load_model(self.model_size, device=self.device)
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading Whisper model: {e}", exc_info=True)
            self.model = None

    def transcribe(self, audio_path: str, language: Optional[str] = None):
        """
        Transcribes audio and returns segments with word timestamps.

        Returns:
            dict: Result with keys:
                - 'segments': List of transcription segments
                - 'text': Full transcription text
                - 'language': Detected language code (ISO 639-1)
                - 'language_probs': Dict of language -> probability scores
        """
        if self.model is None:
            raise Exception("Whisper model failed to load.")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Ensure we are using absolute path for safety
        audio_path = os.path.abspath(audio_path)

        settings = get_settings()

        options: dict[str, Any] = {
            "word_timestamps": True,
            "fp16": self.fp16,
            "condition_on_previous_text": settings.whisper_condition_on_previous_text,
        }
        if language:
            options["language"] = language
        if settings.whisper_hallucination_silence_threshold is not None:
            options["hallucination_silence_threshold"] = (
                settings.whisper_hallucination_silence_threshold
            )

        logger.info(f"Starting transcription for: {audio_path}")
        result = self.model.transcribe(audio_path, **options)
        logger.info(f"Transcription completed: {len(result.get('segments', []))} segments")

        # Extract language detection probabilities
        # Run language detection to get full probability distribution
        try:
            audio = whisper.load_audio(audio_path)
            audio = whisper.pad_or_trim(audio)
            mel = whisper.log_mel_spectrogram(audio).to(self.model.device)

            # detect_language returns (detected_lang, probability_dict)
            # Type cast to handle LSP type inference issues
            lang_detection_result = cast(
                Tuple[str, Dict[str, float]], self.model.detect_language(mel)
            )

            # Extract probability dict from the tuple
            probs = lang_detection_result[1]

            # Convert to regular dict (from torch tensor if needed)
            language_probs: Dict[str, float] = {}
            for lang, prob in probs.items():
                # Safely handle both torch tensor and regular float types
                prob_tensor = getattr(prob, "item", None)
                if callable(prob_tensor):
                    prob_value = float(prob_tensor())
                else:
                    prob_value = float(prob)
                language_probs[str(lang)] = prob_value  # type: ignore[arg-type]

            result["language_probs"] = language_probs

            # Ensure language field is set from detection result
            if "language" not in result or result["language"] is None:
                detected_lang = lang_detection_result[0]
                result["language"] = detected_lang

            detected_confidence = language_probs.get(str(result["language"]), 0.0)
            logger.info(
                f"Detected language: {result['language']} "
                f"with confidence: {detected_confidence:.2%}"
            )

        except Exception as e:
            logger.warning(f"Failed to detect language probabilities: {e}")
            result["language_probs"] = {}
            if "language" not in result or result["language"] is None:
                result["language"] = language or "ja"

        # Clean Whisper output: remove bracket annotations like [掌声], [音楽], etc.
        self._clean_segments(result)

        return result

    def _clean_segments(self, result: dict) -> None:
        """
        Remove Whisper's bracket annotations from segments.

        Whisper inserts bracket-annotated non-speech events like [applause],
        [laughter], [music] which are not useful for shadow reading practice.

        Args:
            result: Whisper transcription result dict (modified in-place)
        """
        segments = result.get("segments", [])
        if not segments:
            return

        cleaned_segments = []
        for segment in segments:
            # Clean segment text
            original_text = segment.get("text", "")
            cleaned_text = clean_whisper_text(original_text)

            # Skip empty segments after cleaning
            if not cleaned_text:
                logger.debug(f"Skipping empty segment after cleaning: {original_text[:50]}...")
                continue

            # Clean individual word texts
            cleaned_words = []
            for word in segment.get("words", []):
                if isinstance(word, dict):
                    cleaned_word_text = clean_whisper_text(word.get("word", ""))
                    if cleaned_word_text:
                        word["word"] = cleaned_word_text
                        cleaned_words.append(word)
                elif hasattr(word, "word"):
                    # Handle object with word attribute
                    cleaned_word_text = clean_whisper_text(word.word)
                    if cleaned_word_text:
                        word.word = cleaned_word_text
                        cleaned_words.append(word)

            segment["text"] = cleaned_text
            if cleaned_words:
                segment["words"] = cleaned_words

            cleaned_segments.append(segment)

        result["segments"] = cleaned_segments

    def load_subtitle(self, subtitle_path: str = None, subtitle_content: str = None) -> dict:
        """
        Load subtitle from file or content string and return in Standard Segment format.

        Args:
            subtitle_path (str): Path to the subtitle file (SRT format).
            subtitle_content (str): Raw subtitle content string (SRT format).

        Returns:
            dict: Result dict with 'segments' key containing parsed subtitle segments.

        Note:
            Either subtitle_path or subtitle_content must be provided.
            If both are provided, subtitle_content takes precedence.
        """
        if subtitle_content is None and subtitle_path is None:
            raise ValueError("Either subtitle_path or subtitle_content must be provided.")

        if subtitle_content is None:
            if not os.path.exists(subtitle_path):
                raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

            # Try different encodings
            encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "shift_jis", "latin-1"]
            content = None
            for encoding in encodings:
                try:
                    with open(subtitle_path, "r", encoding=encoding) as f:
                        content = f.read()
                    logger.debug(f"Successfully decoded subtitle with encoding: {encoding}")
                    break
                except UnicodeDecodeError:
                    logger.debug(f"Failed to decode with encoding: {encoding}")
                    continue

            if content is None:
                logger.error(
                    f"Could not decode subtitle file with any supported encoding: {subtitle_path}"
                )
                raise ValueError(
                    f"Could not decode subtitle file with any supported encoding: {subtitle_path}"
                )

            subtitle_content = content

        segments = parse_srt(subtitle_content)

        if not segments:
            logger.error("No valid subtitle segments found in the provided content")
            raise ValueError("No valid subtitle segments found in the provided content.")

        logger.info(f"Loaded {len(segments)} subtitle segments from user-provided file")

        return {"segments": segments}
