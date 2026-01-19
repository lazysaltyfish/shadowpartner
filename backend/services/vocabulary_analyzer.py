"""Vocabulary analyzer service using Gemini AI.

This module analyzes Japanese subtitles to extract valuable vocabulary
for learners, focusing on N1/N2 level words and business expressions.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from google import genai

from settings import get_settings
from utils.logger import get_logger
from utils.resilience import retry_on_http_errors

logger = get_logger(__name__)

# Prompt template for vocabulary analysis
VOCABULARY_ANALYSIS_PROMPT = """You are a highly experienced Japanese Language Teacher
specializing in Business Japanese and JLPT N1/N2 preparation.

# Task
Analyze the Japanese subtitles and extract valuable vocabulary for advanced learners.

# Filtering Criteria

EXCLUDE:
- Basic pronouns (私, あなた, 彼, 私達)
- Basic particles (は, が, を, に, で, と) unless part of a grammar point
- Simple daily verbs (食べる, 寝る, 行く, 来る, ある, いる) unless used idiomatically
- Filler words (あの, えーと, その, この)
- Proper nouns (names, places) unless they contain useful vocabulary
- Numbers and counters
- Basic adjectives (良い, 悪い, 高い, 低い)

INCLUDE:
- JLPT N1/N2 vocabulary
- Keigo (honorifics) and business expressions (恐縮, 承知, 存じ上げる)
- Yojijukugo (four-character idioms)
- Business terminology (稟議, 根回し, 善処, 納期)
- Compound verbs and collocations (気を配る, 足を運ぶ, 耳を疑う)
- Suru-verbs used in business contexts (対応, 検討, 提案)

# Output Format
Output ONLY a valid JSON array. Do not include markdown formatting (no ```json or ```),
do not include conversational text.

Each item should have:
- word: dictionary form (基本形)
- surface_form: original form as it appears in subtitle (文中形式)
- reading: hiragana reading
- part_of_speech: Noun/Verb/Keigo/Idiom/Suru-verb/etc
- jlpt_level: "N1", "N2", "N3", "N4", "N5", or "Business"
- meaning_cn: Chinese definition
- meaning_en: English definition
- original_sentence: the exact sentence from subtitle
- timestamp: time position (use the time from the input)
- learning_note: brief usage/grammar explanation in Japanese or Chinese

# Example

Input:
[04:20] 昨日の会議で、部長がその件を承諾されたそうです。
[04:25] 正直、耳を疑いましたよ。
[04:30] やっぱり、根回しが重要なんですね。

Output:
[
  {{
    "word": "承諾",
    "surface_form": "承諾された",
    "reading": "しょうだく",
    "part_of_speech": "Noun / Suru-verb",
    "jlpt_level": "N1",
    "meaning_cn": "承诺，答应，同意",
    "meaning_en": "consent, agreement, approval",
    "original_sentence": "昨日の会議で、部長がその件を承諾されたそうです。",
    "timestamp": "04:20",
    "learning_note": "正式な場面で「引き受ける」「同意する」という意味で使われる硬い表現。"
  }},
  {{
    "word": "耳を疑う",
    "surface_form": "耳を疑いました",
    "reading": "みみをうたがう",
    "part_of_speech": "Idiom",
    "jlpt_level": "N2",
    "meaning_cn": "难以置信，怀疑自己的耳朵",
    "meaning_en": "to not believe one's ears",
    "original_sentence": "正直、耳を疑いましたよ。",
    "timestamp": "04:25",
    "learning_note": "信じられないような話を聞いた時に使う慣用句。"
  }},
  {{
    "word": "根回し",
    "surface_form": "根回し",
    "reading": "ねまわし",
    "part_of_speech": "Noun",
    "jlpt_level": "Business",
    "meaning_cn": "事前疏通，打通关节",
    "meaning_en": "laying the groundwork, behind-the-scenes negotiation",
    "original_sentence": "やっぱり、根回しが重要なんですね。",
    "timestamp": "04:30",
    "learning_note": "日本企業文化特有の言葉。会議などで提案を通すために、"
    "事前に主要な人々と話し合っておくこと。"
  }}
]

# Subtitles to Analyze
{subtitles}
"""


class VocabularyAnalyzer:
    """Analyzes Japanese subtitles to extract vocabulary for learners."""

    def __init__(self, executor: Optional[ThreadPoolExecutor] = None):
        """Initialize the vocabulary analyzer.

        Args:
            executor: Thread pool executor for async operations.
        """
        settings = get_settings()
        api_key = settings.gemini_api_key

        # Set timeout before creating client so it can be used in client config
        self.request_timeout_seconds = 120  # Longer timeout for analysis

        self.client = None
        if api_key:
            self.client = genai.Client(
                api_key=api_key,
                http_options={"timeout": self.request_timeout_seconds},
            )
        self.available = bool(api_key)
        self.model_id = settings.gemini_model_id
        self.executor = executor
        logger.info(f"VocabularyAnalyzer initialized with model: {self.model_id}")

    def set_executor(self, executor: Optional[ThreadPoolExecutor]) -> None:
        """Set the thread pool executor."""
        self.executor = executor

    def _format_subtitles(self, segments: List[dict]) -> str:
        """Format subtitle segments for the prompt.

        Args:
            segments: List of subtitle segments with start, end, text.

        Returns:
            Formatted string with timestamps and text.
        """
        lines = []
        for seg in segments:
            start = seg.get("start", 0)
            # Format timestamp as MM:SS
            minutes = int(start // 60)
            seconds = int(start % 60)
            timestamp = f"{minutes:02d}:{seconds:02d}"
            # Get text - could be words or segment text
            text = seg.get("text", "")
            # For word-level segments, join the words
            if not text and "words" in seg:
                text = "".join(w.get("text", "") for w in seg["words"])
            lines.append(f"[{timestamp}] {text}")
        return "\n".join(lines)

    @retry_on_http_errors()
    def _generate_content(self, prompt: str) -> str:
        """Generate content using Gemini API.

        Args:
            prompt: The prompt to send.

        Returns:
            The generated text response.
        """
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
        )
        return response.text.strip()

    def _parse_json_response(self, response_text: str) -> List[dict]:
        """Parse the JSON response from Gemini.

        Args:
            response_text: Raw response text.

        Returns:
            Parsed list of vocabulary items.
        """
        try:
            # Try to parse as-is
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            # Try to find any JSON array
            array_match = re.search(r"\[.*?\]", response_text, re.DOTALL)
            if array_match:
                try:
                    return json.loads(array_match.group(0))
                except json.JSONDecodeError:
                    pass
            logger.error(f"Failed to parse vocabulary response: {response_text[:500]}")
            return []

    def _parse_timestamp(self, timestamp_str: str) -> float:
        """Parse timestamp string to seconds.

        Supports formats:
        - MM:SS or M:SS (e.g., "04:20", "4:20")
        - MM:SS.sss or M:SS.sss (e.g., "04:20.5", "4:20.500")
        - HH:MM:SS or H:M:SS (e.g., "01:04:20")
        - HH:MM:SS.sss (e.g., "01:04:20.5")

        Args:
            timestamp_str: Timestamp string from AI response.

        Returns:
            Time in seconds, or 0.0 if parsing fails.
        """
        try:
            # Clean the input - remove any whitespace
            timestamp_str = timestamp_str.strip()

            # Split by colon
            parts = timestamp_str.split(":")

            if len(parts) == 2:
                # MM:SS format
                minutes = float(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            elif len(parts) == 3:
                # HH:MM:SS format
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds

            logger.warning(f"Unrecognized timestamp format: {timestamp_str}")
            return 0.0
        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse timestamp '{timestamp_str}': {e}")
            return 0.0

    def analyze(self, segments: List[dict]) -> List[dict]:
        """Analyze subtitle segments to extract vocabulary.

        Args:
            segments: List of subtitle segments with start, end, text/words.

        Returns:
            List of vocabulary items with word, reading, meaning, etc.
        """
        if not self.available:
            logger.warning("Gemini API Key missing. Skipping vocabulary analysis.")
            return []

        if not segments:
            return []

        logger.info(f"Starting vocabulary analysis for {len(segments)} segments")

        # Format subtitles for the prompt
        formatted_subs = self._format_subtitles(segments)

        try:
            prompt = VOCABULARY_ANALYSIS_PROMPT.format(subtitles=formatted_subs)
            response_text = self._generate_content(prompt)
            vocab_items = self._parse_json_response(response_text)

            # Post-process: add timing information
            for item in vocab_items:
                timestamp_str = item.get("timestamp", "")
                if timestamp_str:
                    item["start_time"] = self._parse_timestamp(timestamp_str)
                else:
                    item["start_time"] = 0.0
                # Set end_time to start_time + 5 seconds as default
                item["end_time"] = item.get("start_time", 0.0) + 5.0

            logger.info(f"Vocabulary analysis completed: {len(vocab_items)} items extracted")
            return vocab_items

        except Exception as e:
            logger.error(f"Vocabulary analysis error: {e}", exc_info=True)
            return []
