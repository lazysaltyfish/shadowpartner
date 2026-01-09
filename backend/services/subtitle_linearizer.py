import re
from typing import List, Dict, Optional

class SubtitleLinearizer:
    """
    Service to linearize scrolling subtitles (e.g. from live streams or ASR)
    by removing overlapping prefixes that match the previous suffix.
    """

    def linearize(self, subtitles: List[Dict]) -> List[Dict]:
        """
        Linearize a list of subtitle segments.
        
        Args:
            subtitles: List of dicts with 'start', 'end', 'text'.
            
        Returns:
            List of linearized subtitle dicts.
        """
        linearized = []
        if not subtitles:
            return linearized

        # 1. Initialization
        # The first subtitle is kept as is (or maybe we should process it if we had history, but here we don't)
        linearized.append(subtitles[0])
        
        # Keep the raw text of the previous segment for comparison
        prev_text_raw = subtitles[0].get('text', '')

        for i in range(1, len(subtitles)):
            curr = subtitles[i]
            curr_text_raw = curr.get('text', '')
            
            # 2. Find Overlap
            # Find the longest suffix of prev_text_raw that matches a prefix of curr_text_raw
            overlap_len = self._find_longest_overlap(prev_text_raw, curr_text_raw)
            
            # 3. Extract New Content
            # The new content is everything after the overlap
            new_content = curr_text_raw[overlap_len:].strip()
            
            # 4. Construct New Segment
            if new_content:
                new_item = {
                    "start": curr["start"],
                    "end": curr["end"],
                    "text": new_content
                }
                # Preserve other fields if any
                for k, v in curr.items():
                    if k not in ["start", "end", "text"]:
                        new_item[k] = v
                linearized.append(new_item)
            else:
                # Fully overlapped / repeated content.
                # In some cases we might want to extend the previous segment's end time,
                # but for now we just skip adding a new segment as per design.
                pass
                
            # 5. Update Context
            # The current raw text becomes the previous raw text for the next iteration
            prev_text_raw = curr_text_raw

        return linearized

    def _find_longest_overlap(self, s1: str, s2: str) -> int:
        """
        Find the length of the longest suffix of s1 that matches a prefix of s2.
        """
        # Optimization: start from the smaller of the two lengths
        max_len = min(len(s1), len(s2))
        
        # Try to match from longest possible overlap down to 1
        for length in range(max_len, 0, -1):
            if s1.endswith(s2[:length]):
                return length
                
        return 0

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
            
            match = re.match(r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})', timestamp_line)
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
