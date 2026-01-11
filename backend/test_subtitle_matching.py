import unittest

from processing import check_subtitle_similarity

class TestSubtitleMatching(unittest.TestCase):
    def test_perfect_match(self):
        gen = [{"text": "こんにちは世界"}, {"text": "これはテストです"}]
        ref = [{"text": "こんにちは世界"}, {"text": "これはテストです"}]
        warnings = check_subtitle_similarity(gen, ref)
        self.assertEqual(len(warnings), 0)

    def test_partial_match_ok(self):
        # Slightly different but high similarity
        gen = [{"text": "こんにちは世界。"}, {"text": "これはテストです。"}]
        ref = [{"text": "こんにちは世界"}, {"text": "これはテスト"}] # Missing punctuation/some chars
        warnings = check_subtitle_similarity(gen, ref, threshold=0.8)
        self.assertEqual(len(warnings), 0)

    def test_mismatch_warning(self):
        gen = [{"text": "こんにちは世界"}]
        ref = [{"text": "さようなら"}] # Completely different
        warnings = check_subtitle_similarity(gen, ref, threshold=0.5)
        self.assertTrue(len(warnings) > 0)
        print(f"\nWarning generated: {warnings[0]}")

    def test_sampling_logic(self):
        # Create a long list to test sampling
        gen = [{"text": f"segment_{i}"} for i in range(100)]
        ref = [{"text": f"segment_{i}"} for i in range(100)]
        warnings = check_subtitle_similarity(gen, ref)
        self.assertEqual(len(warnings), 0)
        
        # Mismatch in the middle shouldn't matter if sampling skips it?
        # Actually sampling takes middle 20%, so it should catch middle mismatches.
        ref_mismatch = [{"text": f"WRONG_{i}"} for i in range(100)]
        warnings = check_subtitle_similarity(gen, ref_mismatch)
        self.assertTrue(len(warnings) > 0)

if __name__ == '__main__':
    unittest.main()
