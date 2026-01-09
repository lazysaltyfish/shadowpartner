import re
from typing import List, Dict, Tuple

class SubtitleLinearizer:
    """
    Service to linearize scrolling subtitles by removing overlapping content
    and tracking character-to-segment mapping for timestamp calibration.
    """

    def linearize(self, subtitles: List[Dict]) -> List[Dict]:
        """
        Linearize a list of subtitle segments (legacy method for compatibility).

        Args:
            subtitles: List of dicts with 'start', 'end', 'text'.

        Returns:
            List of linearized subtitle dicts with deduplicated text.
        """
        if not subtitles:
            return []

        merged_text, char_metadata = self.deduplicate_with_metadata(subtitles)

        # Rebuild segments from deduplicated text
        return self._rebuild_simple_segments(merged_text, char_metadata, subtitles)

    def deduplicate_with_metadata(self, subtitles: List[Dict]) -> Tuple[str, List[Dict]]:
        """
        Deduplicate scrolling subtitles and track character origins.

        Args:
            subtitles: List of dicts with 'start', 'end', 'text'.

        Returns:
            Tuple of:
            - merged_text: The deduplicated complete text
            - char_metadata: List of dicts for each char with seg_idx, seg_start, seg_end
        """
        if not subtitles:
            return "", []

        merged_text = ""
        char_metadata = []

        for seg_idx, seg in enumerate(subtitles):
            text = seg.get('text', '')
            seg_start = seg.get('start', 0.0)
            seg_end = seg.get('end', 0.0)

            if not text:
                continue

            # Find overlap between merged text and current segment
            overlap_len = self._find_overlap_at_end(merged_text, text)

            # Only add new content (after the overlap)
            new_content = text[overlap_len:]

            for char in new_content:
                merged_text += char
                char_metadata.append({
                    'seg_idx': seg_idx,
                    'seg_start': seg_start,
                    'seg_end': seg_end
                })

        return merged_text, char_metadata

    def _find_overlap_at_end(self, s1: str, s2: str) -> int:
        """
        Find the length of the longest suffix of s1 that matches a prefix of s2.

        Example:
            s1 = "今日は天気が"
            s2 = "天気がいい"
            Returns: 3 (matching "天気が")
        """
        if not s1 or not s2:
            return 0

        max_len = min(len(s1), len(s2))

        for length in range(max_len, 0, -1):
            if s1.endswith(s2[:length]):
                return length

        return 0

    def _rebuild_simple_segments(self, merged_text: str, char_metadata: List[Dict],
                                  original_segments: List[Dict]) -> List[Dict]:
        """
        Rebuild segment list from deduplicated text (for legacy compatibility).
        Each segment contains only its unique (non-overlapping) content.
        """
        if not merged_text:
            return []

        # Group characters by their source segment
        from collections import defaultdict
        segments_chars = defaultdict(list)

        for i, (char, meta) in enumerate(zip(merged_text, char_metadata)):
            seg_idx = meta['seg_idx']
            segments_chars[seg_idx].append({
                'char': char,
                'seg_start': meta['seg_start'],
                'seg_end': meta['seg_end']
            })

        # Build result segments
        result = []
        for seg_idx in sorted(segments_chars.keys()):
            chars = segments_chars[seg_idx]
            text = "".join(c['char'] for c in chars).strip()

            if text:
                result.append({
                    'text': text,
                    'start': chars[0]['seg_start'],
                    'end': chars[-1]['seg_end'],
                    'words': []  # Will be populated by calibration
                })

        return result

    @staticmethod
    def parse_srt_time(time_str: str) -> float:
        """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
        time_str = time_str.replace(',', '.')
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds

    def parse_srt(self, content: str) -> List[Dict]:
        """
        Parse SRT content into a list of segments.
        """
        segments = []
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        blocks = re.split(r'\n\n+', content.strip())

        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue

            timestamp_idx = -1
            for i, line in enumerate(lines):
                if ' --> ' in line:
                    timestamp_idx = i
                    break

            if timestamp_idx == -1:
                continue

            timestamp_line = lines[timestamp_idx]
            text_lines = lines[timestamp_idx + 1:]

            match = re.match(
                r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})',
                timestamp_line
            )
            if not match:
                continue

            start_time = self.parse_srt_time(match.group(1))
            end_time = self.parse_srt_time(match.group(2))
            text = ' '.join(text_lines).strip()

            if not text:
                continue

            segments.append({
                'text': text,
                'start': start_time,
                'end': end_time
            })

        return segments
