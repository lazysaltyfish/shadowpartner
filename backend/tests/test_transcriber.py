import os
import sys
import unittest

# Add backend to sys path to import services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transcriber import clean_whisper_text


class TestCleanWhisperText(unittest.TestCase):
    """Test cases for the clean_whisper_text function."""

    def test_normal_text_unchanged(self):
        """Normal text without brackets should remain unchanged."""
        self.assertEqual(clean_whisper_text("こんにちは世界"), "こんにちは世界")
        self.assertEqual(clean_whisper_text("Hello World"), "Hello World")
        self.assertEqual(clean_whisper_text(""), "")

    def test_single_bracket_removal(self):
        """Single bracket content should be removed."""
        self.assertEqual(clean_whisper_text("こんにちは[音楽]世界"), "こんにちは世界")
        self.assertEqual(clean_whisper_text("Hello[music]World"), "HelloWorld")

    def test_multiple_brackets(self):
        """Multiple bracket contents should all be removed."""
        self.assertEqual(
            clean_whisper_text("[掌声]こんにちは[音楽]世界[笑い声]"),
            "こんにちは世界",
        )
        self.assertEqual(clean_whisper_text("[applause]Hello[laughter]World[music]"), "HelloWorld")

    def test_bracket_at_edges(self):
        """Bracket content at start or end should be removed."""
        self.assertEqual(clean_whisper_text("[音楽]こんにちは"), "こんにちは")
        self.assertEqual(clean_whisper_text("こんにちは[音楽]"), "こんにちは")

    def test_japanese_brackets(self):
        """Japanese-style brackets 【...】 should also be removed."""
        self.assertEqual(clean_whisper_text("こんにちは【音楽】世界"), "こんにちは世界")
        self.assertEqual(clean_whisper_text("【掌声】こんにちは【笑い声】"), "こんにちは")

    def test_mixed_brackets(self):
        """Both [...] and 【...】 should be removed together."""
        self.assertEqual(clean_whisper_text("こんにちは[音楽]世界【音楽】"), "こんにちは世界")

    def test_empty_after_cleaning(self):
        """Text that becomes empty after cleaning should return empty string."""
        self.assertEqual(clean_whisper_text("[掌声]"), "")
        self.assertEqual(clean_whisper_text("【音楽】"), "")
        self.assertEqual(clean_whisper_text("[applause][laughter][music]"), "")

    def test_multiple_spaces_cleaned(self):
        """Multiple spaces around removed content should be cleaned to single space."""
        self.assertEqual(clean_whisper_text("こんにちは [音楽] 世界"), "こんにちは 世界")
        # After bracket removal, multiple spaces become single space
        self.assertEqual(clean_whisper_text("Hello  [music]  World"), "Hello World")

    def test_special_characters_in_brackets(self):
        """Special characters inside brackets should be removed."""
        self.assertEqual(clean_whisper_text("こんにちは[!!!]世界"), "こんにちは世界")
        self.assertEqual(clean_whisper_text("Hello[中文]World"), "HelloWorld")

    def test_unicode_brackets(self):
        """Various Unicode bracket styles should be handled."""
        # Full-width brackets
        self.assertEqual(clean_whisper_text("こんにちは［音楽］世界"), "こんにちは世界")


class TestCleanSegmentsIntegration(unittest.TestCase):
    """Integration tests for segment cleaning in the transcriber."""

    def test_clean_segments_basic(self):
        """Test basic segment cleaning functionality."""
        from services.transcriber import AudioTranscriber

        # Create a mock result similar to Whisper output
        mock_result = {
            "segments": [
                {
                    "text": "こんにちは[音楽]世界",
                    "start": 0.0,
                    "end": 3.0,
                    "words": [
                        {"word": "こんにちは", "start": 0.0, "end": 1.0},
                        {"word": "[音楽]", "start": 1.0, "end": 2.0},
                        {"word": "世界", "start": 2.0, "end": 3.0},
                    ],
                },
                {
                    "text": "[掌声]Hello",
                    "start": 3.0,
                    "end": 5.0,
                    "words": [
                        {"word": "[掌声]", "start": 3.0, "end": 4.0},
                        {"word": "Hello", "start": 4.0, "end": 5.0},
                    ],
                },
            ]
        }

        # Create transcriber instance (without loading model)
        transcriber = AudioTranscriber.__new__(AudioTranscriber)
        transcriber._clean_segments(mock_result)

        # Check that brackets are removed from segments
        self.assertEqual(mock_result["segments"][0]["text"], "こんにちは世界")
        self.assertEqual(mock_result["segments"][1]["text"], "Hello")

        # Check that empty words are removed
        self.assertEqual(len(mock_result["segments"][0]["words"]), 2)
        self.assertEqual(mock_result["segments"][0]["words"][0]["word"], "こんにちは")
        self.assertEqual(mock_result["segments"][0]["words"][1]["word"], "世界")

        # Check that segments that become empty are removed
        self.assertEqual(len(mock_result["segments"]), 2)  # Second segment still has content

    def test_clean_segments_all_empty(self):
        """Test that segments becoming entirely empty are handled."""
        from services.transcriber import AudioTranscriber

        mock_result = {
            "segments": [
                {
                    "text": "[掌声]",
                    "start": 0.0,
                    "end": 1.0,
                    "words": [{"word": "[掌声]", "start": 0.0, "end": 1.0}],
                }
            ]
        }

        transcriber = AudioTranscriber.__new__(AudioTranscriber)
        transcriber._clean_segments(mock_result)

        # Entirely empty segment should be removed
        self.assertEqual(len(mock_result["segments"]), 0)

    def test_clean_segments_no_change(self):
        """Test that clean segments remain unchanged."""
        from services.transcriber import AudioTranscriber

        mock_result = {
            "segments": [
                {
                    "text": "こんにちは世界",
                    "start": 0.0,
                    "end": 3.0,
                    "words": [
                        {"word": "こんにちは", "start": 0.0, "end": 1.5},
                        {"word": "世界", "start": 1.5, "end": 3.0},
                    ],
                }
            ]
        }

        transcriber = AudioTranscriber.__new__(AudioTranscriber)
        original_segments = mock_result["segments"].copy()
        transcriber._clean_segments(mock_result)

        # Should remain unchanged
        self.assertEqual(mock_result["segments"], original_segments)


if __name__ == "__main__":
    unittest.main()
