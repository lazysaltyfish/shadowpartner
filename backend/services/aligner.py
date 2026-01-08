import difflib

class Aligner:
    def align(self, whisper_words, mecab_tokens, segment_start: float = None, segment_end: float = None):
        """
        Aligns timestamps from whisper words to mecab tokens.
        whisper_words: list of {'word': str, 'start': float, 'end': float}
        mecab_tokens: list of {'text': str, 'reading': str}
        segment_start: Optional segment start time (used when whisper_words is empty)
        segment_end: Optional segment end time (used when whisper_words is empty)
        Returns: mecab_tokens with 'start' and 'end' keys added.
        """
        if not mecab_tokens:
            return []
        if not whisper_words:
            # If no whisper words but we have segment timestamps, distribute time evenly across tokens
            if segment_start is not None and segment_end is not None:
                total_chars = sum(len(t['text']) for t in mecab_tokens)
                if total_chars == 0:
                    for t in mecab_tokens:
                        t['start'] = segment_start
                        t['end'] = segment_end
                else:
                    duration = segment_end - segment_start
                    current_time = segment_start
                    for t in mecab_tokens:
                        char_count = len(t['text'])
                        token_duration = (char_count / total_chars) * duration
                        t['start'] = current_time
                        t['end'] = current_time + token_duration
                        current_time = t['end']
            else:
                # No timestamps available at all
                for t in mecab_tokens:
                    t['start'] = 0.0
                    t['end'] = 0.0
            return mecab_tokens

        # 1. Flatten Whisper words into a char-level map
        whisper_chars = []
        for word in whisper_words:
            w_text = word['word'].strip()
            if not w_text: continue
            w_start = word['start']
            w_end = word['end']
            duration = w_end - w_start
            char_len = len(w_text)
            if char_len == 0: continue
            char_dur = duration / char_len
            
            for i, char in enumerate(w_text):
                whisper_chars.append({
                    'char': char,
                    'start': w_start + (i * char_dur),
                    'end': w_start + ((i+1) * char_dur)
                })
        
        # 2. Flatten MeCab tokens
        mecab_chars = []
        for idx, token in enumerate(mecab_tokens):
            text = token['text']
            for char in text:
                mecab_chars.append({
                    'char': char,
                    'token_index': idx
                })

        # 3. Align using SequenceMatcher
        w_str = "".join([c['char'] for c in whisper_chars])
        m_str = "".join([c['char'] for c in mecab_chars])
        
        matcher = difflib.SequenceMatcher(None, m_str, w_str)
        
        # Initialize tokens with None
        for token in mecab_tokens:
            token['start'] = None
            token['end'] = None

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Match found
                for k in range(i2 - i1):
                    m_idx = i1 + k
                    w_idx = j1 + k
                    
                    # Safety check
                    if m_idx >= len(mecab_chars) or w_idx >= len(whisper_chars):
                        continue

                    token_idx = mecab_chars[m_idx]['token_index']
                    w_char_data = whisper_chars[w_idx]
                    
                    token = mecab_tokens[token_idx]
                    
                    if token['start'] is None or w_char_data['start'] < token['start']:
                        token['start'] = w_char_data['start']
                    
                    if token['end'] is None or w_char_data['end'] > token['end']:
                        token['end'] = w_char_data['end']
        
        # 4. Interpolation / Fill Gaps
        # We need a reference start time for the first token if it wasn't matched
        current_time = 0.0
        if whisper_chars:
            current_time = whisper_chars[0]['start']
        
        for i, token in enumerate(mecab_tokens):
            # If start is missing
            if token['start'] is None:
                token['start'] = current_time
            
            # If end is missing
            if token['end'] is None:
                # Try to find next valid start
                next_start = None
                for j in range(i + 1, len(mecab_tokens)):
                    if mecab_tokens[j]['start'] is not None:
                        next_start = mecab_tokens[j]['start']
                        break
                
                if next_start is not None:
                    token['end'] = next_start
                else:
                    # If no next valid start, guess a small duration or use last valid end
                    token['end'] = token['start'] + 0.1 
            
            # Update current_time for next iteration
            current_time = token['end']
            
            # Final sanity check: end >= start
            if token['end'] < token['start']:
                token['end'] = token['start']

        return mecab_tokens
