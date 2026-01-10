import threading

import MeCab

from utils.logger import get_logger

# Setup logger
logger = get_logger(__name__)


class JapaneseAnalyzer:
    def __init__(self):
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
        """
        Analyzes Japanese text and returns list of dicts: {'text': surface, 'reading': hiragana}.
        """
        # Use a thread-local Tagger for safe concurrent analysis.
        tagger = self._get_tagger()
        node = tagger.parseToNode(text)
        result = []
        
        while node:
            surface = node.surface
            feature_str = node.feature
            
            # Skip empty nodes (BOS/EOS usually has empty surface in some versions, or specific feature)
            # But relying on feature string is safer for BOS/EOS detection if surface is not empty.
            if not surface:
                node = node.next
                continue
                
            features = feature_str.split(",")
            
            # Attempt to extract reading. 
            # With unidic-lite, the features are extensive.
            # Index 9 is usually pronunciation (katakana).
            # If unknown, it might be '*' or just short.
            
            reading = surface # Default fallback
            
            if len(features) > 9:
                cand = features[9]
                if cand and cand != "*":
                    reading = cand
            elif len(features) > 7: # Maybe ipadic format?
                 cand = features[7]
                 if cand and cand != "*":
                    reading = cand
            
            # If the surface contains Kanji but reading is same as surface, something is wrong or it's not a standard word.
            # But we leave it as is for robustness.
            
            # Convert to Hiragana
            reading_hira = self._katakana_to_hiragana(reading)
            
            # If surface is already Kana/Punctuation, reading might be same. 
            # We can optionally hide reading if it's identical to text to clean up UI, 
            # but let's leave that decision to Frontend or keep it consistent.
            # Actually, usually Furigana is NOT shown if text == reading.
            # Let's keep it here, Frontend can decide to hide <rt> if text==reading.
            
            result.append({
                "text": surface,
                "reading": reading_hira
            })
            
            node = node.next
            
        return result

    def _katakana_to_hiragana(self, text):
        result = ""
        for char in text:
            code = ord(char)
            # Katakana range: U+30A1 - U+30F6
            if 0x30A1 <= code <= 0x30F6:
                result += chr(code - 0x60)
            else:
                result += char
        return result
