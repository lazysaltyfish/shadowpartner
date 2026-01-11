import difflib
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

# Setup logger
logger = get_logger(__name__)


class Aligner:
    """
    Aligns AI-generated timestamps to reference subtitle text.
    Handles scrolling subtitle deduplication and word-level timestamp calibration.
    """

    def calibrate_from_merged(
        self,
        merged_text: str,
        char_metadata: List[Dict],
        generated_segments: List[Dict]
    ) -> Tuple[str, List[Dict]]:
        """
        Calibrate timestamps for deduplicated reference text using AI-generated timestamps.

        Args:
            merged_text: Deduplicated text from SubtitleLinearizer
            char_metadata: Metadata for each char (seg_idx, seg_start, seg_end)
            generated_segments: AI-generated segments with word-level timestamps

        Returns:
            Tuple of (merged_text, char_timestamps) where char_timestamps contains
            start/end times for each character
        """
        if not merged_text or not generated_segments:
            return merged_text, []

        # 1. Flatten AI segments to character-level timestamps
        ai_chars = self._flatten_ai_segments(generated_segments)

        if not ai_chars:
            # Fallback: distribute time evenly
            return merged_text, self._distribute_time_evenly(
                merged_text, char_metadata
            )

        # 2. Normalize both texts for matching (remove spaces, punctuation variations)
        ref_normalized, ref_mapping = self._normalize_text(merged_text)
        ai_text = "".join(c['char'] for c in ai_chars)
        ai_normalized, ai_mapping = self._normalize_text(ai_text)

        # 3. Align using SequenceMatcher
        char_timestamps = [None] * len(merged_text)
        matcher = difflib.SequenceMatcher(None, ref_normalized, ai_normalized)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for k in range(i2 - i1):
                    ref_norm_idx = i1 + k
                    ai_norm_idx = j1 + k

                    # Map back to original indices
                    ref_orig_idx = ref_mapping[ref_norm_idx]
                    ai_orig_idx = ai_mapping[ai_norm_idx]

                    if ai_orig_idx < len(ai_chars):
                        # Get segment boundaries for clamping
                        meta = char_metadata[ref_orig_idx]
                        seg_start = meta['seg_start']
                        seg_end = meta['seg_end']

                        # Clamp timestamps to segment boundaries
                        start = ai_chars[ai_orig_idx]['start']
                        end = ai_chars[ai_orig_idx]['end']
                        start = max(seg_start, min(start, seg_end))
                        end = max(seg_start, min(end, seg_end))
                        if start > end:
                            end = start

                        char_timestamps[ref_orig_idx] = {
                            'start': start,
                            'end': end
                        }

        # 4. Interpolate gaps
        self._interpolate_timestamps(char_timestamps, char_metadata)

        return merged_text, char_timestamps

    def _flatten_ai_segments(self, segments: List[Dict]) -> List[Dict]:
        """Flatten AI segments to character-level timestamps."""
        chars = []

        for seg in segments:
            words = seg.get('words', [])

            if not words:
                # Fallback: distribute segment time over text
                text = seg.get('text', '')
                start = seg.get('start', 0.0)
                end = seg.get('end', 0.0)

                if text:
                    duration = end - start
                    char_dur = duration / len(text) if len(text) > 0 else 0
                    for i, char in enumerate(text):
                        chars.append({
                            'char': char,
                            'start': start + i * char_dur,
                            'end': start + (i + 1) * char_dur
                        })
            else:
                for word in words:
                    w_text = word.get('word', '')
                    w_start = word.get('start', 0.0)
                    w_end = word.get('end', 0.0)

                    if not w_text:
                        continue

                    w_dur = w_end - w_start
                    char_dur = w_dur / len(w_text)

                    for i, char in enumerate(w_text):
                        chars.append({
                            'char': char,
                            'start': w_start + i * char_dur,
                            'end': w_start + (i + 1) * char_dur
                        })

        return chars

    def _normalize_text(self, text: str) -> Tuple[str, List[int]]:
        """
        Normalize text for better matching.
        Returns normalized text and mapping from normalized index to original index.
        """
        normalized = []
        mapping = []

        for i, char in enumerate(text):
            # Skip spaces and some punctuation for matching
            if char in ' \t\n\r　':
                continue
            normalized.append(char)
            mapping.append(i)

        return ''.join(normalized), mapping

    def _distribute_time_evenly(
        self,
        text: str,
        char_metadata: List[Dict]
    ) -> List[Dict]:
        """Distribute time evenly when no AI timestamps available."""
        if not text or not char_metadata:
            return []

        seg_chars = defaultdict(list)

        for i, meta in enumerate(char_metadata):
            seg_chars[meta['seg_idx']].append((i, meta))

        result = [None] * len(text)

        for seg_idx in sorted(seg_chars.keys()):
            chars = seg_chars[seg_idx]
            if not chars:
                continue

            seg_start = chars[0][1]['seg_start']
            seg_end = chars[0][1]['seg_end']
            duration = seg_end - seg_start
            char_dur = duration / len(chars) if chars else 0

            for j, (orig_idx, meta) in enumerate(chars):
                result[orig_idx] = {
                    'start': seg_start + j * char_dur,
                    'end': seg_start + (j + 1) * char_dur
                }

        return result

    def _interpolate_timestamps(
        self,
        timestamps: List[Optional[Dict]],
        char_metadata: List[Dict]
    ):
        """
        Fill gaps in timestamps using smart interpolation.

        For unrecognized characters, interpolate based on neighboring
        recognized characters' timestamps, distributing time proportionally.
        """
        if not timestamps:
            return

        n = len(timestamps)

        # First pass: identify all gaps (consecutive None values)
        gaps = []
        i = 0
        while i < n:
            if timestamps[i] is None:
                gap_start = i
                while i < n and timestamps[i] is None:
                    i += 1
                gap_end = i
                gaps.append((gap_start, gap_end))
            else:
                i += 1

        # Second pass: fill each gap using surrounding timestamps
        for gap_start, gap_end in gaps:
            gap_length = gap_end - gap_start

            # Find previous valid timestamp
            prev_time = None
            if gap_start > 0 and timestamps[gap_start - 1] is not None:
                prev_time = timestamps[gap_start - 1]['end']

            # Find next valid timestamp
            next_time = None
            if gap_end < n and timestamps[gap_end] is not None:
                next_time = timestamps[gap_end]['start']

            # Determine interpolation bounds
            if prev_time is None and next_time is None:
                # No surrounding timestamps, use segment bounds
                seg_start = char_metadata[gap_start]['seg_start']
                seg_end = char_metadata[gap_end - 1]['seg_end']
                prev_time = seg_start
                next_time = seg_end
            elif prev_time is None:
                # No previous timestamp, use segment start as lower bound
                seg_start = char_metadata[gap_start]['seg_start']
                prev_time = max(seg_start, next_time - gap_length * 0.1)
            elif next_time is None:
                # No next timestamp (gap at end of text)
                # Use the last segment's end time as upper bound
                seg_end = char_metadata[gap_end - 1]['seg_end']
                next_time = seg_end

            # Ensure prev_time <= next_time
            if prev_time > next_time:
                # Timestamps might be out of order, use midpoint
                mid = (prev_time + next_time) / 2
                prev_time = mid
                next_time = mid

            # Distribute time evenly across the gap
            total_duration = next_time - prev_time
            char_duration = total_duration / gap_length if gap_length > 0 else 0

            for j in range(gap_length):
                idx = gap_start + j
                start = prev_time + j * char_duration
                end = prev_time + (j + 1) * char_duration

                timestamps[idx] = {'start': start, 'end': end}

    def rebuild_segments_with_timestamps(
        self,
        merged_text: str,
        char_metadata: List[Dict],
        char_timestamps: List[Dict]
    ) -> List[Dict]:
        """
        Rebuild segment structure from calibrated character data.

        Returns list of segments with 'text', 'start', 'end', 'words' (char-level).
        """
        if not merged_text:
            return []

        seg_chars = defaultdict(list)

        for i, (char, meta, ts) in enumerate(
            zip(merged_text, char_metadata, char_timestamps)
        ):
            seg_idx = meta['seg_idx']
            seg_chars[seg_idx].append({
                'char': char,
                'start': ts['start'] if ts else meta['seg_start'],
                'end': ts['end'] if ts else meta['seg_end']
            })

        result = []
        for seg_idx in sorted(seg_chars.keys()):
            chars = seg_chars[seg_idx]
            if not chars:
                continue

            text = "".join(c['char'] for c in chars)
            if not text.strip():
                continue

            # Create word entries (character-level for now)
            words = [
                {'word': c['char'], 'start': c['start'], 'end': c['end']}
                for c in chars
            ]

            result.append({
                'text': text,
                'start': chars[0]['start'],
                'end': chars[-1]['end'],
                'words': words
            })

        return result

    # Legacy method for backward compatibility
    def calibrate(
        self,
        reference_segments: List[Dict],
        generated_segments: List[Dict]
    ) -> List[Dict]:
        """
        Legacy calibration method.
        Flattens reference segments and calibrates against AI segments.
        """
        # Flatten reference to single text stream
        ref_text = ""
        ref_metadata = []

        for seg_idx, seg in enumerate(reference_segments):
            text = seg.get('text', '')
            seg_start = seg.get('start', 0.0)
            seg_end = seg.get('end', 0.0)

            for char in text:
                ref_text += char
                ref_metadata.append({
                    'seg_idx': seg_idx,
                    'seg_start': seg_start,
                    'seg_end': seg_end
                })

        # Calibrate
        _, char_timestamps = self.calibrate_from_merged(
            ref_text, ref_metadata, generated_segments
        )

        # Convert to legacy format
        result = []
        for i, (char, ts) in enumerate(zip(ref_text, char_timestamps)):
            if ts:
                result.append({
                    'word': char,
                    'start': ts['start'],
                    'end': ts['end']
                })
            else:
                meta = ref_metadata[i]
                result.append({
                    'word': char,
                    'start': meta['seg_start'],
                    'end': meta['seg_end']
                })

        return result

    def align(
        self,
        whisper_words: List[Dict],
        mecab_tokens: List[Dict],
        segment_start: float = None,
        segment_end: float = None
    ) -> List[Dict]:
        """
        Aligns timestamps from whisper words (or calibrated characters) to mecab tokens.

        Args:
            whisper_words: list of {'word': str, 'start': float, 'end': float}
            mecab_tokens: list of {'text': str, 'reading': str}
            segment_start: Optional segment start time
            segment_end: Optional segment end time

        Returns:
            mecab_tokens with 'start' and 'end' keys added.
        """
        if not mecab_tokens:
            return []

        if not whisper_words:
            return self._align_without_timestamps(
                mecab_tokens, segment_start, segment_end
            )

        # Flatten whisper words to char-level
        whisper_chars = []
        for word in whisper_words:
            w_text = word.get('word', '').strip()
            if not w_text:
                continue

            w_start = word.get('start', 0.0)
            w_end = word.get('end', 0.0)
            duration = w_end - w_start
            char_dur = duration / len(w_text) if w_text else 0

            for i, char in enumerate(w_text):
                whisper_chars.append({
                    'char': char,
                    'start': w_start + i * char_dur,
                    'end': w_start + (i + 1) * char_dur
                })

        # Flatten mecab tokens
        mecab_chars = []
        for idx, token in enumerate(mecab_tokens):
            for char in token.get('text', ''):
                mecab_chars.append({
                    'char': char,
                    'token_index': idx
                })

        # Align using SequenceMatcher
        w_str = "".join(c['char'] for c in whisper_chars)
        m_str = "".join(c['char'] for c in mecab_chars)

        matcher = difflib.SequenceMatcher(None, m_str, w_str)

        # Initialize tokens
        for token in mecab_tokens:
            token['start'] = None
            token['end'] = None

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for k in range(i2 - i1):
                    m_idx = i1 + k
                    w_idx = j1 + k

                    if m_idx >= len(mecab_chars) or w_idx >= len(whisper_chars):
                        continue

                    token_idx = mecab_chars[m_idx]['token_index']
                    w_data = whisper_chars[w_idx]
                    token = mecab_tokens[token_idx]

                    if token['start'] is None or w_data['start'] < token['start']:
                        token['start'] = w_data['start']

                    if token['end'] is None or w_data['end'] > token['end']:
                        token['end'] = w_data['end']

        # Fill gaps
        self._fill_token_gaps(mecab_tokens, whisper_chars)

        return mecab_tokens

    def _align_without_timestamps(
        self,
        mecab_tokens: List[Dict],
        segment_start: float,
        segment_end: float
    ) -> List[Dict]:
        """Distribute time evenly when no timestamps available."""
        if segment_start is not None and segment_end is not None:
            total_chars = sum(len(t.get('text', '')) for t in mecab_tokens)

            if total_chars == 0:
                for t in mecab_tokens:
                    t['start'] = segment_start
                    t['end'] = segment_end
            else:
                duration = segment_end - segment_start
                current = segment_start

                for t in mecab_tokens:
                    char_count = len(t.get('text', ''))
                    token_dur = (char_count / total_chars) * duration
                    t['start'] = current
                    t['end'] = current + token_dur
                    current = t['end']
        else:
            for t in mecab_tokens:
                t['start'] = 0.0
                t['end'] = 0.0

        return mecab_tokens

    def _fill_token_gaps(
        self,
        tokens: List[Dict],
        whisper_chars: List[Dict]
    ):
        """Fill gaps in token timestamps."""
        current_time = whisper_chars[0]['start'] if whisper_chars else 0.0

        for i, token in enumerate(tokens):
            if token['start'] is None:
                token['start'] = current_time

            if token['end'] is None:
                # Find next valid start
                next_start = None
                for j in range(i + 1, len(tokens)):
                    if tokens[j]['start'] is not None:
                        next_start = tokens[j]['start']
                        break

                if next_start is not None:
                    token['end'] = next_start
                else:
                    token['end'] = token['start'] + 0.1

            current_time = token['end']

            if token['end'] < token['start']:
                token['end'] = token['start']
