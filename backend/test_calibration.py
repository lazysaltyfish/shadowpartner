import os
import sys
import unittest

# Add backend to sys path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.aligner import Aligner
from services.subtitle_linearizer import SubtitleLinearizer


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.aligner = Aligner()
        self.linearizer = SubtitleLinearizer()

    def test_basic_calibration(self):
        """Test basic calibration with legacy method."""
        reference_segments = [{
            'text': '猫が好き',
            'start': 1.0,
            'end': 5.0
        }]

        generated_segments = [{
            'text': '猫が好き',
            'start': 1.5,
            'end': 4.5,
            'words': [
                {'word': '猫', 'start': 1.5, 'end': 2.0},
                {'word': 'が', 'start': 2.0, 'end': 3.0},
                {'word': '好き', 'start': 3.5, 'end': 4.5}
            ]
        }]

        calibrated = self.aligner.calibrate(reference_segments, generated_segments)

        self.assertEqual(len(calibrated), 4)
        chars = [c['word'] for c in calibrated]
        self.assertEqual("".join(chars), "猫が好き")

        # Check timestamp transfer
        self.assertAlmostEqual(calibrated[0]['start'], 1.5)
        self.assertAlmostEqual(calibrated[0]['end'], 2.0)
        self.assertAlmostEqual(calibrated[1]['start'], 2.0)
        self.assertAlmostEqual(calibrated[1]['end'], 3.0)

    def test_calibrate_from_merged(self):
        """Test the new calibrate_from_merged method."""
        merged_text = "猫が好き"
        char_metadata = [
            {'seg_idx': 0, 'seg_start': 1.0, 'seg_end': 5.0},
            {'seg_idx': 0, 'seg_start': 1.0, 'seg_end': 5.0},
            {'seg_idx': 0, 'seg_start': 1.0, 'seg_end': 5.0},
            {'seg_idx': 0, 'seg_start': 1.0, 'seg_end': 5.0},
        ]

        generated_segments = [{
            'text': '猫が好き',
            'start': 1.5,
            'end': 4.5,
            'words': [
                {'word': '猫', 'start': 1.5, 'end': 2.0},
                {'word': 'が', 'start': 2.0, 'end': 3.0},
                {'word': '好き', 'start': 3.5, 'end': 4.5}
            ]
        }]

        _, char_timestamps = self.aligner.calibrate_from_merged(
            merged_text, char_metadata, generated_segments
        )

        self.assertEqual(len(char_timestamps), 4)
        self.assertAlmostEqual(char_timestamps[0]['start'], 1.5)
        self.assertAlmostEqual(char_timestamps[0]['end'], 2.0)

    def test_boundary_clamping(self):
        # Reference: "AB" (10.0 - 11.0)
        reference_segments = [{
            'text': 'AB',
            'start': 10.0,
            'end': 11.0
        }]

        # Generated: "AB" (9.0 - 12.0) -> Way outside
        generated_segments = [{
            'text': 'AB',
            'start': 9.0,
            'end': 12.0,
            'words': [
                {'word': 'A', 'start': 9.0, 'end': 9.5},
                {'word': 'B', 'start': 11.5, 'end': 12.0}
            ]
        }]

        calibrated = self.aligner.calibrate(reference_segments, generated_segments)

        # 'A' should be clamped to start >= 10.0
        self.assertGreaterEqual(calibrated[0]['start'], 10.0)
        
        # 'B' should be clamped to end <= 11.0
        self.assertLessEqual(calibrated[1]['end'], 11.0)

    def test_interpolation(self):
        # Reference: "ABC" (0.0 - 3.0)
        reference_segments = [{
            'text': 'ABC',
            'start': 0.0,
            'end': 3.0
        }]

        # Generated: "AC" (Matched only A and C)
        # A: 0.0-1.0
        # C: 2.0-3.0
        # B is missing in generated or didn't match
        generated_segments = [{
            'text': 'AC',
            'start': 0.0,
            'end': 3.0,
            'words': [
                {'word': 'A', 'start': 0.0, 'end': 1.0},
                {'word': 'C', 'start': 2.0, 'end': 3.0}
            ]
        }]

        calibrated = self.aligner.calibrate(reference_segments, generated_segments)
        
        # B should exist
        self.assertEqual(calibrated[1]['word'], 'B')
        
        # B should be interpolated between A's end (1.0) and C's start (2.0)
        self.assertGreaterEqual(calibrated[1]['start'], 1.0)
        self.assertLessEqual(calibrated[1]['end'], 2.0)

    def test_end_to_end_scrolling_subtitle(self):
        """Test complete flow: scrolling subtitle -> dedupe -> calibrate."""
        # Simulate scrolling subtitles
        scrolling_subs = [
            {"start": 0.0, "end": 1.0, "text": "今日は"},
            {"start": 1.0, "end": 2.0, "text": "今日は天気"},
            {"start": 2.0, "end": 3.0, "text": "天気がいい"}
        ]

        # AI generated with timestamps
        ai_segments = [{
            'text': '今日は天気がいい',
            'start': 0.0,
            'end': 3.0,
            'words': [
                {'word': '今日は', 'start': 0.0, 'end': 1.0},
                {'word': '天気が', 'start': 1.0, 'end': 2.0},
                {'word': 'いい', 'start': 2.0, 'end': 3.0}
            ]
        }]

        # Step 1: Deduplicate
        merged, metadata = self.linearizer.deduplicate_with_metadata(scrolling_subs)
        self.assertEqual(merged, "今日は天気がいい")

        # Step 2: Calibrate
        _, timestamps = self.aligner.calibrate_from_merged(merged, metadata, ai_segments)
        self.assertEqual(len(timestamps), len(merged))

        # Step 3: Rebuild segments
        segments = self.aligner.rebuild_segments_with_timestamps(merged, metadata, timestamps)
        self.assertGreater(len(segments), 0)

        # Verify timestamps are reasonable
        for seg in segments:
            self.assertGreaterEqual(seg['start'], 0.0)
            self.assertLessEqual(seg['end'], 3.0)


if __name__ == '__main__':
    unittest.main()