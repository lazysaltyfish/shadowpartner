import difflib

class Aligner:
    def calibrate(self, reference_segments: list, generated_segments: list) -> list:
        """
        Hybrid Timestamp Calibration:
        Aligns generated AI timestamps to reference subtitle text.
        
        Args:
            reference_segments: List of dicts {'text': str, 'start': float, 'end': float} (User/SRT)
            generated_segments: List of dicts {'text': str, 'words': List[...]} (Whisper AI)
            
        Returns:
            List of {'word': str, 'start': float, 'end': float} representing character-level timestamps
            for the reference text, suitable for passing to align() as whisper_words.
        """
        # 1. Flatten Generated Segments -> Characters with timestamps
        gen_chars = []
        for seg in generated_segments:
            words = seg.get('words', [])
            # Fallback if no words (shouldn't happen with word_timestamps=True, but safety first)
            if not words:
                # Distribute segment duration over characters
                text = seg.get('text', '')
                start = seg.get('start', 0.0)
                end = seg.get('end', 0.0)
                if not text: continue
                duration = end - start
                char_dur = duration / len(text)
                for i, char in enumerate(text):
                    gen_chars.append({
                        'char': char,
                        'start': start + i * char_dur,
                        'end': start + (i + 1) * char_dur
                    })
            else:
                for word in words:
                    w_text = word['word']
                    w_start = word['start']
                    w_end = word['end']
                    w_dur = w_end - w_start
                    if not w_text: continue
                    c_dur = w_dur / len(w_text)
                    for i, char in enumerate(w_text):
                        gen_chars.append({
                            'char': char,
                            'start': w_start + i * c_dur,
                            'end': w_start + (i + 1) * c_dur
                        })

        # 2. Flatten Reference Segments -> Characters with segment constraints
        ref_chars = []
        for seg in reference_segments:
            text = seg.get('text', '')
            seg_start = seg.get('start', 0.0)
            seg_end = seg.get('end', 0.0)
            
            # Clean text slightly to match better (optional, but spaces often mess up diffs if inconsistent)
            # But we want to preserve original text for output.
            # We'll strip for matching but keep original structure.
            
            for char in text:
                ref_chars.append({
                    'char': char,
                    'seg_start': seg_start,
                    'seg_end': seg_end,
                    'start': None,
                    'end': None
                })

        # 3. Align Character Streams
        gen_str = "".join(c['char'] for c in gen_chars)
        ref_str = "".join(c['char'] for c in ref_chars)
        
        matcher = difflib.SequenceMatcher(None, ref_str, gen_str)
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for k in range(i2 - i1):
                    r_idx = i1 + k
                    g_idx = j1 + k
                    # Transfer timestamps
                    ref_chars[r_idx]['start'] = gen_chars[g_idx]['start']
                    ref_chars[r_idx]['end'] = gen_chars[g_idx]['end']
        
        # 4. Interpolation and Constraint Enforcement
        # We process each reference segment independently to ensure we don't bleed across segment boundaries?
        # Actually, iterating linearly is fine, as long as we clamp to seg_start/seg_end.
        
        # Fill None values
        last_valid_end = 0.0
        # Forward pass to fill starts/ends
        for i, rc in enumerate(ref_chars):
            if rc['start'] is None:
                # Look ahead for next valid start
                next_start = None
                steps = 0
                for j in range(i + 1, len(ref_chars)):
                    if ref_chars[j]['start'] is not None:
                        next_start = ref_chars[j]['start']
                        steps = j - i
                        break
                
                if next_start is not None:
                    # Interpolate
                    # If last_valid_end is far behind (e.g. previous segment), this might stretch.
                    # But we will clamp later.
                    prev_time = last_valid_end
                    if prev_time < rc['seg_start']: # Ensure we don't start before segment
                         prev_time = rc['seg_start']
                    
                    gap = next_start - prev_time
                    step_size = gap / (steps + 1)
                    rc['start'] = prev_time + step_size
                    rc['end'] = rc['start'] + step_size
                else:
                    # No future timestamp found, use segment end or fallback
                    rc['start'] = max(last_valid_end, rc['seg_start'])
                    rc['end'] = rc['start'] + 0.1 # Arbitrary small duration
            
            # Clamp to Segment Boundaries
            if rc['start'] < rc['seg_start']:
                rc['start'] = rc['seg_start']
            if rc['start'] > rc['seg_end']:
                rc['start'] = rc['seg_end']
                
            if rc['end'] > rc['seg_end']:
                rc['end'] = rc['seg_end']
            if rc['end'] < rc['seg_start']:
                rc['end'] = rc['seg_start']
            
            # Sanity: start <= end
            if rc['start'] > rc['end']:
                # If we clamped both to seg_end, this might happen if original start > end (unlikely)
                # or if start was clamped to seg_end and end was also clamped to seg_end.
                # Just sync them.
                rc['end'] = rc['start']
                
            last_valid_end = rc['end']

        # 5. Convert back to "Words" format for align()
        # Since we are essentially passing characters, each "word" is a character.
        calibrated_words = []
        for rc in ref_chars:
            calibrated_words.append({
                'word': rc['char'],
                'start': rc['start'],
                'end': rc['end']
            })
            
        return calibrated_words

    def align(self, whisper_words, mecab_tokens, segment_start: float = None, segment_end: float = None):
        """
        Aligns timestamps from whisper words (or calibrated characters) to mecab tokens.
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
