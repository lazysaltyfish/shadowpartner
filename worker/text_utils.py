import re
from typing import Any, Dict


def clean_whisper_text(text: str) -> str:
    """Remove bracket annotations from Whisper output."""
    if not text:
        return text

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

        segment["text"] = cleaned_text
        if cleaned_words:
            segment["words"] = cleaned_words

        cleaned_segments.append(segment)

    result["segments"] = cleaned_segments
