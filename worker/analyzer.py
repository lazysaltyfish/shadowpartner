import threading

import MeCab

from logger import get_logger

logger = get_logger(__name__)


class JapaneseAnalyzer:
    def __init__(self) -> None:
        self._local = threading.local()
        self._tagger_args = None
        try:
            self._local.tagger = MeCab.Tagger()
            logger.info("MeCab initialized successfully")
        except RuntimeError as e:
            logger.warning(f"MeCab default init failed, trying fallback: {e}")
            self._tagger_args = "-r /dev/null"
            self._local.tagger = MeCab.Tagger(self._tagger_args)
            logger.info("MeCab initialized with fallback configuration")

    def _get_tagger(self):
        tagger = getattr(self._local, "tagger", None)
        if tagger is None:
            tagger = MeCab.Tagger(self._tagger_args) if self._tagger_args else MeCab.Tagger()
            self._local.tagger = tagger
        return tagger

    def analyze(self, text: str):
        """Analyze Japanese text into surface/reading tokens."""
        tagger = self._get_tagger()
        node = tagger.parseToNode(text)
        result = []

        while node:
            surface = node.surface
            feature_str = node.feature

            if not surface:
                node = node.next
                continue

            features = feature_str.split(",")
            reading = surface

            if len(features) > 9:
                cand = features[9]
                if cand and cand != "*":
                    reading = cand
            elif len(features) > 7:
                cand = features[7]
                if cand and cand != "*":
                    reading = cand

            reading_hira = self._katakana_to_hiragana(reading)
            result.append({"text": surface, "reading": reading_hira})

            node = node.next

        return result

    def analyze_batch(self, texts):
        return [self.analyze(text) if text else [] for text in texts]

    def _katakana_to_hiragana(self, text):
        result = ""
        for char in text:
            code = ord(char)
            if 0x30A1 <= code <= 0x30F6:
                result += chr(code - 0x60)
            else:
                result += char
        return result
