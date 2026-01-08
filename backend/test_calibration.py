import unittest
import sys
import os

# Add backend to sys path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.aligner import Aligner

class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.aligner = Aligner()

    def test_basic_calibration(self):
        # Reference: "猫が好き" (1.0 - 5.0)
        reference_segments = [{
            'text': '猫が好き',
            'start': 1.0,
            'end': 5.0
        }]

        # Generated: "猫が 好き" (1.5 - 4.5)
        # Word 1: "猫が" (1.5 - 3.0)
        # Word 2: "好き" (3.5 - 4.5)
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

        # Check total length
        self.assertEqual(len(calibrated), 4) # 猫, が, 好, き

        # Check chars
        chars = [c['word'] for c in calibrated]
        self.assertEqual("".join(chars), "猫が好き")

        # Check timestamp transfer
        # '猫' should inherit start=1.5, end=2.0
        self.assertAlmostEqual(calibrated[0]['start'], 1.5)
        self.assertAlmostEqual(calibrated[0]['end'], 2.0)
        
        # 'が' should inherit start=2.0, end=3.0
        self.assertAlmostEqual(calibrated[1]['start'], 2.0)
        self.assertAlmostEqual(calibrated[1]['end'], 3.0)

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

if __name__ == '__main__':
    unittest.main()