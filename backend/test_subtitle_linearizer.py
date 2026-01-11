import os
import sys
import unittest

# Add backend to sys path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.subtitle_linearizer import SubtitleLinearizer


class TestSubtitleLinearizer(unittest.TestCase):
    def setUp(self):
        self.linearizer = SubtitleLinearizer()

    def test_standard_scrolling(self):
        """
        Test the standard scrolling pattern where the end of one segment
        overlaps with the beginning of the next.
        """
        # Case 1: Standard Scrolling
        # In: ["A", "A B", "B C"]
        # Out: ["A", "B", "C"]
        
        subtitles = [
            {"start": 1.0, "end": 2.0, "text": "A"},
            {"start": 2.0, "end": 3.0, "text": "A B"},
            {"start": 3.0, "end": 4.0, "text": "B C"}
        ]
        
        result = self.linearizer.linearize(subtitles)
        
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['text'], "A")
        self.assertEqual(result[1]['text'], "B")
        self.assertEqual(result[2]['text'], "C")

    def test_full_repetition(self):
        """
        Test when a segment is fully contained/repeated in the next, 
        or simply repeated.
        """
        # Case 2: Full Repetition
        # In: ["Hello", "Hello", "Hello World"]
        # Out: ["Hello", "World"]
        
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.0, "text": "Hello"},
            {"start": 2.0, "end": 3.0, "text": "Hello World"}
        ]
        
        result = self.linearizer.linearize(subtitles)
        
        # Expectation: 
        # 1. "Hello" (kept)
        # 2. "Hello" (overlap "Hello", new "") -> Skipped because new content is empty
        # 3. "Hello World" (overlap "Hello", new " World" -> strip -> "World") -> Kept
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['text'], "Hello")
        self.assertEqual(result[1]['text'], "World")
        
        # Verify timestamps are preserved for the segments that are kept
        self.assertEqual(result[0]['start'], 0.0)
        self.assertEqual(result[1]['start'], 2.0)

    def test_no_overlap(self):
        """Test when there is no text overlap between segments."""
        # Case 3: No Overlap
        # In: ["Hello", "World"]
        # Out: ["Hello", "World"]
        
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "Hello"},
            {"start": 1.0, "end": 2.0, "text": "World"}
        ]
        
        result = self.linearizer.linearize(subtitles)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['text'], "Hello")
        self.assertEqual(result[1]['text'], "World")

    def test_empty_input(self):
        """Test handling of empty input list."""
        result = self.linearizer.linearize([])
        self.assertEqual(result, [])

    def test_mv_example_simulation(self):
        """
        Test simulating a real-world scenario like an MV or live stream.
        """
        # Segment 1: "I'm looking for" (T1)
        # Segment 2: "looking for a sign" (T2)
        # Segment 3: "for a sign of life" (T3)
        
        subtitles = [
            {"start": 1.0, "end": 2.0, "text": "I'm looking for"},
            {"start": 2.0, "end": 3.0, "text": "looking for a sign"},
            {"start": 3.0, "end": 4.0, "text": "for a sign of life"}
        ]
        
        result = self.linearizer.linearize(subtitles)
        
        # 1. "I'm looking for"
        # 2. "looking for a sign". Overlap: "looking for" (len 11).
        #    New: " a sign". Strip -> "a sign"
        # 3. "for a sign of life". Overlap: "for a sign" (len 10).
        #    New: " of life". Strip -> "of life"
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['text'], "I'm looking for")
        self.assertEqual(result[1]['text'], "a sign")
        self.assertEqual(result[2]['text'], "of life")

    def test_overlap_helper(self):
        """Test the _find_overlap_at_end helper method directly."""
        s1 = "Hello world"
        s2 = "world is great"
        # Overlap: "world" (5 chars)
        overlap = self.linearizer._find_overlap_at_end(s1, s2)
        self.assertEqual(overlap, 5)

        s1 = "abcde"
        s2 = "cdefg"
        # Overlap: "cde" (3 chars)
        overlap = self.linearizer._find_overlap_at_end(s1, s2)
        self.assertEqual(overlap, 3)

        s1 = "abc"
        s2 = "xyz"
        overlap = self.linearizer._find_overlap_at_end(s1, s2)
        self.assertEqual(overlap, 0)

        # Test case where suffix is shorter than prefix
        s1 = "end"
        s2 = "ending"
        # overlap "end" (3)
        overlap = self.linearizer._find_overlap_at_end(s1, s2)
        self.assertEqual(overlap, 3)

    def test_real_world_jitter(self):
        """
        Test with slight variations/junk characters if we were handling them (Optional).
        Since current implementation is strict, we test strict behavior.
        """
        # "Hello world." vs "world. It's me"
        # Note the period.
        s1 = "Hello world."
        s2 = "world. It's me"
        
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": s1},
            {"start": 1.0, "end": 2.0, "text": s2}
        ]
        
        result = self.linearizer.linearize(subtitles)
        # Overlap "world." (6 chars)
        # New " It's me" -> "It's me"
        
        self.assertEqual(result[1]['text'], "It's me")

    def test_deduplicate_with_metadata(self):
        """Test the new deduplicate_with_metadata method."""
        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "今日は"},
            {"start": 1.0, "end": 2.0, "text": "今日は天気が"},
            {"start": 2.0, "end": 3.0, "text": "天気がいい"},
            {"start": 3.0, "end": 4.0, "text": "いいですね"}
        ]

        merged_text, char_metadata = self.linearizer.deduplicate_with_metadata(subtitles)

        # Expected merged text: "今日は天気がいいですね"
        self.assertEqual(merged_text, "今日は天気がいいですね")
        self.assertEqual(len(char_metadata), len(merged_text))

        # Check metadata tracking
        # "今日は" from segment 0
        self.assertEqual(char_metadata[0]['seg_idx'], 0)
        self.assertEqual(char_metadata[1]['seg_idx'], 0)
        self.assertEqual(char_metadata[2]['seg_idx'], 0)

        # "天気が" from segment 1
        self.assertEqual(char_metadata[3]['seg_idx'], 1)

    def test_deduplicate_preserves_timestamps(self):
        """Test that metadata preserves original segment timestamps."""
        subtitles = [
            {"start": 10.0, "end": 15.0, "text": "ABC"},
            {"start": 15.0, "end": 20.0, "text": "BCDE"}
        ]

        merged_text, char_metadata = self.linearizer.deduplicate_with_metadata(subtitles)

        # "A" from seg 0, "BC" overlap, "DE" from seg 1
        # Merged: "ABCDE"
        self.assertEqual(merged_text, "ABCDE")

        # Check timestamps are preserved
        self.assertEqual(char_metadata[0]['seg_start'], 10.0)
        self.assertEqual(char_metadata[0]['seg_end'], 15.0)

        # "DE" should be from segment 1
        self.assertEqual(char_metadata[3]['seg_start'], 15.0)
        self.assertEqual(char_metadata[4]['seg_start'], 15.0)


if __name__ == '__main__':
    unittest.main()