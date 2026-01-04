import MeCab
import re

class JapaneseAnalyzer:
    def __init__(self):
        # Initializing MeCab. 
        # Note: In some environments, arguments might be needed like '-r /etc/mecabrc' 
        # but with mecab-python3 + unidic-lite, no args is usually best.
        try:
            self.tagger = MeCab.Tagger() 
        except RuntimeError:
            # Fallback attempts if default init fails
            self.tagger = MeCab.Tagger("-r /dev/null")

    def analyze(self, text: str):
        """
        Analyzes Japanese text and returns list of dicts: {'text': surface, 'reading': hiragana}.
        """
        # MeCab isn't thread safe in older versions, but Tagger object should be fine if local or careful.
        # For this simple app, it's okay.
        
        node = self.tagger.parseToNode(text)
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
