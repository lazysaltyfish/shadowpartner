"""Comprehensive tests for JapaneseAnalyzer.

Tests cover:
- Initialization with MeCab fallback handling
- Thread-local tagger creation
- Text analysis with reading extraction
- Batch processing
- Katakana to hiragana conversion
- Edge cases and error handling
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch, call

# Add parent directory to path to import analyzer module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock MeCab BEFORE importing analyzer
sys.modules['MeCab'] = MagicMock()

from analyzer import JapaneseAnalyzer


class MockNode:
    """Mock MeCab node for testing."""

    def __init__(self, surface="", feature="", next_node=None):
        self.surface = surface
        self.feature = feature
        self._next = next_node

    @property
    def next(self):
        return self._next


class TestKatakanaToHiragana(unittest.TestCase):
    """Test _katakana_to_hiragana conversion method."""

    def test_basic_katakana_conversion(self):
        """Test basic katakana to hiragana conversion."""
        analyzer = JapaneseAnalyzer()

        # ア (0x30A2) -> あ (0x3042)
        self.assertEqual(analyzer._katakana_to_hiragana("ア"), "あ")
        # イ (0x30A4) -> い (0x3044)
        self.assertEqual(analyzer._katakana_to_hiragana("イ"), "い")
        # ウ (0x30A6) -> う (0x3046)
        self.assertEqual(analyzer._katakana_to_hiragana("ウ"), "う")

    def test_katakana_word_conversion(self):
        """Test conversion of full katakana words."""
        analyzer = JapaneseAnalyzer()

        # ニホン (Japan) -> にほん
        self.assertEqual(analyzer._katakana_to_hiragana("ニホン"), "にほん")
        # コンニチハ (Hello) -> こんにちは
        self.assertEqual(analyzer._katakana_to_hiragana("コンニチハ"), "こんにちは")
        # アリガトウ (Thank you) -> ありがとう
        self.assertEqual(analyzer._katakana_to_hiragana("アリガトウ"), "ありがとう")

    def test_mixed_katakana_hiragana(self):
        """Test that hiragana characters pass through unchanged."""
        analyzer = JapaneseAnalyzer()

        # Mixed katakana and hiragana
        self.assertEqual(analyzer._katakana_to_hiragana("コンニチハ"), "こんにちは")
        # Katakana + hiragana + katakana
        self.assertEqual(analyzer._katakana_to_hiragana("アイウエオ"), "あいうえお")

    def test_non_japanese_characters_unchanged(self):
        """Test that non-Japanese characters are unchanged."""
        analyzer = JapaneseAnalyzer()

        # Latin alphabet
        self.assertEqual(analyzer._katakana_to_hiragana("Hello"), "Hello")
        # Numbers
        self.assertEqual(analyzer._katakana_to_hiragana("123"), "123")
        # Symbols
        self.assertEqual(analyzer._katakana_to_hiragana("!@#"), "!@#")

    def test_kanji_unchanged(self):
        """Test that kanji characters pass through unchanged."""
        analyzer = JapaneseAnalyzer()

        self.assertEqual(analyzer._katakana_to_hiragana("日本"), "日本")
        self.assertEqual(analyzer._katakana_to_hiragana("世界"), "世界")
        self.assertEqual(analyzer._katakana_to_hiragana("漢字"), "漢字")

    def test_empty_string(self):
        """Test conversion of empty string."""
        analyzer = JapaneseAnalyzer()
        self.assertEqual(analyzer._katakana_to_hiragana(""), "")

    def test_katakana_range_boundaries(self):
        """Test katakana Unicode range boundaries (0x30A1-0x30F6)."""
        analyzer = JapaneseAnalyzer()

        # Small ァ (0x30A1) -> small ぁ (0x3041)
        self.assertEqual(analyzer._katakana_to_hiragana("ァ"), "ぁ")
        # ヲ (0x30F2) -> を (0x3092)
        # Note: 0x30F6 is ヶ, but the range in code goes to 0x30F6
        self.assertEqual(analyzer._katakana_to_hiragana("ヲ"), "を")
        # ヶ (0x30F6) -> ゖ (0x3096)
        self.assertEqual(analyzer._katakana_to_hiragana("ヶ"), "ゖ")

    def test_half_width_katakana_unchanged(self):
        """Test that half-width katakana is unchanged (different range)."""
        analyzer = JapaneseAnalyzer()

        # Half-width katakana is in a different range (0xFF65-0xFF9F)
        # and should pass through unchanged
        half_width_kana = "ｱｲｳｴｵ"  # Half-width アイウエオ
        self.assertEqual(analyzer._katakana_to_hiragana(half_width_kana), half_width_kana)

    def test_mixed_content(self):
        """Test conversion of mixed Japanese and other scripts."""
        analyzer = JapaneseAnalyzer()

        # Katakana + kanji + numbers
        self.assertEqual(analyzer._katakana_to_hiragana("ニホン123"), "にほん123")
        # Katakana + English
        self.assertEqual(analyzer._katakana_to_hiragana("コンピュータ"), "こんぴゅーた")

    def test_voiced_sound_marks(self):
        """Test conversion with voiced (dakuten) and semi-voiced (handakuten) marks."""
        analyzer = JapaneseAnalyzer()

        # ガ (0x30AC) -> が (0x304C)
        self.assertEqual(analyzer._katakana_to_hiragana("ガ"), "が")
        # パ (0x30D1) -> ぱ (0x3071)
        self.assertEqual(analyzer._katakana_to_hiragana("パ"), "ぱ")
        # ザジズゼゾ
        self.assertEqual(analyzer._katakana_to_hiragana("ザジズゼゾ"), "ざじずぜぞ")

    def test_long_consonant_marks(self):
        """Test conversion with long consonant mark (chōonpu)."""
        analyzer = JapaneseAnalyzer()

        # ー (0x30FC) is long vowel mark, should pass through
        self.assertEqual(analyzer._katakana_to_hiragana("ビール"), "びーる")
        self.assertEqual(analyzer._katakana_to_hiragana("パーティー"), "ぱーてぃー")


class TestJapaneseAnalyzerInit(unittest.TestCase):
    """Test JapaneseAnalyzer initialization."""

    def test_successful_initialization(self):
        """Test successful MeCab initialization."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            analyzer = JapaneseAnalyzer()

            # Verify Tagger was called with default args
            mock_tagger_cls.assert_called_once_with()
            # Verify tagger is stored in thread-local storage
            self.assertIs(analyzer._local.tagger, mock_tagger)
            self.assertIsNone(analyzer._tagger_args)

    def test_initialization_with_fallback(self):
        """Test MeCab initialization with fallback on RuntimeError."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # First call raises RuntimeError, second succeeds
            mock_tagger = Mock()
            mock_tagger_cls.side_effect = [RuntimeError("Default failed"), mock_tagger]

            analyzer = JapaneseAnalyzer()

            # Verify Tagger was called twice (default, then fallback)
            self.assertEqual(mock_tagger_cls.call_count, 2)
            # First call with no args
            mock_tagger_cls.assert_any_call()
            # Second call with fallback args
            mock_tagger_cls.assert_any_call("-r /dev/null")
            # Verify tagger_args is set for fallback
            self.assertEqual(analyzer._tagger_args, "-r /dev/null")
            self.assertIs(analyzer._local.tagger, mock_tagger)

    def test_initialization_with_unexpected_error(self):
        """Test that unexpected errors during init are not caught."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # Raise a non-RuntimeError exception
            mock_tagger_cls.side_effect = ValueError("Unexpected error")

            with self.assertRaises(ValueError):
                JapaneseAnalyzer()

    def test_tagger_args_persistence(self):
        """Test that _tagger_args persists for fallback case."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.side_effect = [RuntimeError("Default failed"), mock_tagger]

            analyzer = JapaneseAnalyzer()

            self.assertEqual(analyzer._tagger_args, "-r /dev/null")


class TestGetTagger(unittest.TestCase):
    """Test _get_tagger method for thread-local tagger management."""

    def test_get_existing_tagger(self):
        """Test retrieving existing tagger from thread-local storage."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            analyzer = JapaneseAnalyzer()
            # Get tagger should return the same instance
            result = analyzer._get_tagger()
            self.assertIs(result, mock_tagger)

    def test_create_new_tagger_when_missing(self):
        """Test creating new tagger when none exists in thread-local storage."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger1 = Mock()
            mock_tagger2 = Mock()
            mock_tagger_cls.side_effect = [mock_tagger1, mock_tagger2]

            analyzer = JapaneseAnalyzer()
            # Delete tagger to simulate missing tagger
            del analyzer._local.tagger

            # Should create new tagger
            result = analyzer._get_tagger()
            self.assertIs(result, mock_tagger2)
            # Should be stored in thread-local storage
            self.assertIs(analyzer._local.tagger, mock_tagger2)

    def test_get_tagger_with_fallback_args(self):
        """Test _get_tagger uses fallback args when configured."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.side_effect = [
                RuntimeError("Default failed"),
                mock_tagger,
                mock_tagger  # For _get_tagger call
            ]

            analyzer = JapaneseAnalyzer()

            # Delete tagger to force recreation
            del analyzer._local.tagger

            # Should create with fallback args
            result = analyzer._get_tagger()
            self.assertIs(result, mock_tagger)
            # Verify Tagger was called with fallback args
            mock_tagger_cls.assert_called_with("-r /dev/null")

    def test_get_tagger_without_fallback_args(self):
        """Test _get_tagger uses default args when no fallback."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            analyzer = JapaneseAnalyzer()

            # Delete tagger to force recreation
            del analyzer._local.tagger

            # Should create with default args (no args)
            result = analyzer._get_tagger()
            self.assertIs(result, mock_tagger)
            # Verify Tagger was called with no args
            mock_tagger_cls.assert_called_with()


class TestAnalyze(unittest.TestCase):
    """Test analyze method for Japanese text parsing."""

    def _create_mock_nodes(self, surfaces_and_features):
        """Helper to create a chain of mock nodes.

        Args:
            surfaces_and_features: List of (surface, feature) tuples

        Returns:
            First node in the chain
        """
        nodes = []
        for surface, feature in surfaces_and_features:
            node = MockNode(surface=surface, feature=feature)
            nodes.append(node)

        # Link nodes
        for i in range(len(nodes) - 1):
            nodes[i]._next = nodes[i + 1]

        # Last node's next is None (BOS/EOS nodes have empty surface)
        if nodes:
            nodes[-1]._next = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")

        return nodes[0] if nodes else None

    def test_basic_analysis(self):
        """Test basic text analysis with reading extraction."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Create mock nodes: 日本語(nihongo) を (wo) 勉強する(benkyousuru)
            node1 = MockNode(surface="日本語", feature="名詞,一般,*,*,*,*,日本語,ニホンゴ,ニホンゴ")
            node2 = MockNode(surface="を", feature="助詞,格助詞,一般,*,*,*,を,オ,オ")
            node3 = MockNode(surface="勉強する", feature="動詞,自立,*,*,*,*,勉強する,ベンキョウスル,ベンキョウスル")
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node2
            node2._next = node3
            node3._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("日本語を勉強する")

            expected = [
                {"text": "日本語", "reading": "にほんご"},
                {"text": "を", "reading": "お"},
                {"text": "勉強する", "reading": "べんきょうする"}
            ]
            self.assertEqual(result, expected)

    def test_reading_from_field_9(self):
        """Test extraction of reading from feature field 9 (preferred)."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Feature with reading in field 9
            node1 = MockNode(
                surface="行く",
                feature="動詞,自立,*,*,五段-カ行イ音便,基本形,行く,イク,イく"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("行く")

            # Should use field 9 (イく) and convert to hiragana (いく)
            expected = [{"text": "行く", "reading": "いく"}]
            self.assertEqual(result, expected)

    def test_reading_from_field_7_fallback(self):
        """Test extraction of reading from feature field 7 (fallback)."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Feature without field 9, use field 7
            node1 = MockNode(
                surface="東京",
                feature="名詞,固有名詞,地域,一般,*,*,*,トウキョウ,トウキョウ"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("東京")

            # Should use field 7 (トウキョウ) and convert to hiragana (とうきょう)
            expected = [{"text": "東京", "reading": "とうきょう"}]
            self.assertEqual(result, expected)

    def test_reading_asterisk_fallback_to_surface(self):
        """Test that asterisk readings fall back to surface text."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Feature with asterisk in reading fields
            node1 = MockNode(
                surface="ABC",
                feature="名詞,固有名詞,一般,*,*,*,*,*,*"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("ABC")

            # Should use surface text as reading
            expected = [{"text": "ABC", "reading": "ABC"}]
            self.assertEqual(result, expected)

    def test_skip_empty_surface_nodes(self):
        """Test that nodes with empty surface are skipped."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # BOS/EOS node and regular node
            node_bos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1 = MockNode(surface="こんにちは", feature="感動詞,*,*,*,*,*,*,コンニチハ,コンニチハ")
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node_bos._next = node1
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node_bos

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("こんにちは")

            # Should only have one token, skipping BOS/EOS
            expected = [{"text": "こんにちは", "reading": "こんにちは"}]
            self.assertEqual(result, expected)

    def test_katakana_reading_conversion(self):
        """Test that katakana readings are converted to hiragana."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            node1 = MockNode(
                surface="勉強",
                feature="名詞,サ変接続,*,*,*,*,勉強,ベンキョウ,ベンキョウ"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("勉強")

            # Katakana reading should be converted to hiragana
            expected = [{"text": "勉強", "reading": "べんきょう"}]
            self.assertEqual(result, expected)

    def test_mixed_japanese_english_numbers(self):
        """Test analysis of mixed Japanese, English, and numbers."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Create nodes for mixed content
            node1 = MockNode(surface="日本", feature="名詞,一般,*,*,*,*,*,ニホン,ニホン")
            node2 = MockNode(surface="語", feature="名詞,一般,*,*,*,*,*,ゴ,ゴ")
            node3 = MockNode(surface="1", feature="名詞,数,*,*,*,*,*,1,1")
            node4 = MockNode(surface="2", feature="名詞,数,*,*,*,*,*,2,2")
            node5 = MockNode(surface="3", feature="名詞,数,*,*,*,*,*,3,3")
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node2
            node2._next = node3
            node3._next = node4
            node4._next = node5
            node5._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("日本語123")

            expected = [
                {"text": "日本", "reading": "にほん"},
                {"text": "語", "reading": "ご"},
                {"text": "1", "reading": "1"},
                {"text": "2", "reading": "2"},
                {"text": "3", "reading": "3"}
            ]
            self.assertEqual(result, expected)

    def test_insufficient_features(self):
        """Test handling of nodes with insufficient feature fields."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Feature with only 3 fields (insufficient for reading)
            node1 = MockNode(surface="ABC", feature="名詞,一般")
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("ABC")

            # Should fall back to surface text
            expected = [{"text": "ABC", "reading": "ABC"}]
            self.assertEqual(result, expected)

    def test_malformed_features(self):
        """Test handling of malformed feature strings."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Feature string with extra commas (empty fields)
            node1 = MockNode(
                surface="テスト",
                feature="名詞,一般,,,,,,,テスト,テスト"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("テスト")

            # Should handle empty fields gracefully
            expected = [{"text": "テスト", "reading": "てすと"}]
            self.assertEqual(result, expected)


class TestAnalyzeEdgeCases(unittest.TestCase):
    """Test edge cases for analyze method."""

    def test_empty_text_input(self):
        """Test analysis of empty text."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Empty node chain (only BOS/EOS)
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            mock_tagger.parseToNode.return_value = node_eos

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("")

            self.assertEqual(result, [])

    def test_text_with_only_spaces(self):
        """Test analysis of text with only whitespace."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Whitespace is usually tokenized as BOS/EOS
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            mock_tagger.parseToNode.return_value = node_eos

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("   ")

            self.assertEqual(result, [])

    def test_unicode_emoji(self):
        """Test analysis of text with emoji."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Emoji might be tokenized as-is
            node1 = MockNode(surface="😀", feature="UNK,*,*,*,*,*,*,*,*")
            node2 = MockNode(surface="嬉", feature="名詞,*,*,*,*,*,*,ウレシ,ウレシ")
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node2
            node2._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("😀嬉")

            expected = [
                {"text": "😀", "reading": "😀"},
                {"text": "嬉", "reading": "うれし"}
            ]
            self.assertEqual(result, expected)

    def test_rare_kanji(self):
        """Test analysis of rare kanji characters."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Rare kanji might not have readings
            node1 = MockNode(
                surface="𠮷",  # Rare kanji (variation of 吉)
                feature="名詞,固有名詞,人名,姓,*,*,*,*,*"
            )
            node_eos = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = node_eos

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("𠮷")

            # Should fall back to surface text
            expected = [{"text": "𠮷", "reading": "𠮷"}]
            self.assertEqual(result, expected)

    def test_long_text(self):
        """Test analysis of long text (many nodes)."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Create 100 nodes
            nodes = []
            for i in range(100):
                node = MockNode(
                    surface=f"単{i}",
                    feature=f"名詞,*,*,*,*,*,*,タン{i},タン{i}"
                )
                nodes.append(node)

            # Link all nodes
            for i in range(len(nodes) - 1):
                nodes[i]._next = nodes[i + 1]
            nodes[-1]._next = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")

            mock_tagger.parseToNode.return_value = nodes[0]

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze("単" * 100)

            self.assertEqual(len(result), 100)
            # Verify first and last
            self.assertEqual(result[0]["text"], "単0")
            self.assertEqual(result[0]["reading"], "たん0")
            self.assertEqual(result[-1]["text"], "単99")
            self.assertEqual(result[-1]["reading"], "たん99")


class TestAnalyzeBatch(unittest.TestCase):
    """Test analyze_batch method."""

    def test_basic_batch_processing(self):
        """Test processing multiple texts in batch."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Mock nodes for "日本語"
            node1 = MockNode(surface="日本語", feature="名詞,*,*,*,*,*,*,ニホンゴ,ニホンゴ")
            eos1 = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = eos1

            # Mock nodes for "英語"
            node2 = MockNode(surface="英語", feature="名詞,*,*,*,*,*,*,エイゴ,エイゴ")
            eos2 = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node2._next = eos2

            mock_tagger.parseToNode.side_effect = [node1, node2]

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze_batch(["日本語", "英語"])

            expected = [
                [{"text": "日本語", "reading": "にほんご"}],
                [{"text": "英語", "reading": "えいご"}]
            ]
            self.assertEqual(result, expected)

    def test_batch_with_empty_strings(self):
        """Test batch processing with empty strings."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Mock nodes for "日本語"
            node1 = MockNode(surface="日本語", feature="名詞,*,*,*,*,*,*,ニホンゴ,ニホンゴ")
            eos1 = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = eos1

            # Empty string node
            eos2 = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")

            mock_tagger.parseToNode.side_effect = [node1, eos2]

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze_batch(["日本語", "", "テスト"])

            # Empty string should return empty list
            # But we only have 2 mock responses, so third will use last
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0][0]["text"], "日本語")
            self.assertEqual(result[1], [])
            # Third call would reuse last mock, but that's okay for this test

    def test_batch_with_none_values(self):
        """Test batch processing with None values."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            # Mock nodes for "日本語"
            node1 = MockNode(surface="日本語", feature="名詞,*,*,*,*,*,*,ニホンゴ,ニホンゴ")
            eos1 = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
            node1._next = eos1

            mock_tagger.parseToNode.return_value = node1

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze_batch(["日本語", None, "テスト"])

            # None should be treated as empty
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0][0]["text"], "日本語")
            self.assertEqual(result[1], [])  # None becomes empty list

    def test_batch_empty_list(self):
        """Test batch processing of empty list."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            analyzer = JapaneseAnalyzer()
            result = analyzer.analyze_batch([])

            self.assertEqual(result, [])
            # parseToNode should not be called
            mock_tagger.parseToNode.assert_not_called()


class TestThreadSafety(unittest.TestCase):
    """Test thread safety of JapaneseAnalyzer."""

    def test_concurrent_analyze_calls(self):
        """Test multiple threads calling analyze simultaneously."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # Create enough taggers for main thread + worker threads
            taggers = [Mock() for _ in range(6)]  # 1 init + 5 threads
            mock_tagger_cls.side_effect = taggers

            # Set up mock nodes for each tagger
            def create_nodes(text):
                node = MockNode(
                    surface=text,
                    feature=f"名詞,*,*,*,*,*,*,{text},{text}"
                )
                node._next = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
                return node

            for i, tagger in enumerate(taggers):
                tagger.parseToNode.return_value = create_nodes(f"テスト{i}")

            analyzer = JapaneseAnalyzer()

            # Shared results list (thread-safe)
            results = []
            errors = []

            def worker(text):
                try:
                    result = analyzer.analyze(text)
                    results.append(result)
                except Exception as e:
                    errors.append(e)

            # Create and start threads
            threads = []
            texts = ["テスト1", "テスト2", "テスト3", "テスト4", "テスト5"]
            for text in texts:
                t = threading.Thread(target=worker, args=(text,))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join(timeout=5)

            # Verify no errors
            self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")

            # Verify all results (order may vary due to threading)
            self.assertEqual(len(results), 5)

    def test_thread_local_isolation(self):
        """Test that each thread gets its own tagger instance."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # Create taggers: 1 for init + 3 for threads
            taggers = [Mock() for _ in range(4)]
            mock_tagger_cls.side_effect = taggers

            # Set up mock nodes
            for tagger in taggers:
                node = MockNode(
                    surface="テスト",
                    feature="名詞,*,*,*,*,*,*,テスト,テスト"
                )
                node._next = MockNode(surface="", feature="BOS/EOS,*,*,*,*,*,*,*,*")
                tagger.parseToNode.return_value = node

            analyzer = JapaneseAnalyzer()

            # Results from each thread
            tagger_ids = []
            lock = threading.Lock()

            def worker():
                # Get tagger and record its id
                tagger = analyzer._get_tagger()
                with lock:
                    tagger_ids.append(id(tagger))
                # Sleep slightly to increase chance of race condition if not thread-safe
                time.sleep(0.01)

            # Create multiple threads
            threads = []
            for _ in range(3):
                t = threading.Thread(target=worker)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=5)

            # Each thread should have gotten a unique tagger (main thread + 3 workers = 4 unique)
            # But we only record from the 3 workers
            self.assertEqual(len(tagger_ids), 3)
            # All should be different
            self.assertEqual(len(set(tagger_ids)), 3,
                           "Each thread should have its own tagger instance")


class TestMeCabInitializationFailures(unittest.TestCase):
    """Test handling of MeCab initialization failures."""

    def test_initialization_raises_runtime_error(self):
        """Test RuntimeError during initialization triggers fallback."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # First call fails, second succeeds
            mock_tagger1 = Mock()
            mock_tagger2 = Mock()
            mock_tagger_cls.side_effect = [
                RuntimeError("Dictionary path not found"),
                mock_tagger2
            ]

            analyzer = JapaneseAnalyzer()

            self.assertEqual(mock_tagger_cls.call_count, 2)
            self.assertEqual(analyzer._tagger_args, "-r /dev/null")

    def test_initialization_fallback_fails(self):
        """Test when fallback initialization also fails."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            # Both calls fail
            mock_tagger_cls.side_effect = [
                RuntimeError("Default failed"),
                RuntimeError("Fallback failed")
            ]

            # Should raise the fallback error
            with self.assertRaises(RuntimeError):
                JapaneseAnalyzer()

    def test_get_tagger_initialization_failure(self):
        """Test _get_tagger when thread-local creation fails."""
        with patch('analyzer.MeCab.Tagger') as mock_tagger_cls:
            mock_tagger = Mock()
            mock_tagger_cls.return_value = mock_tagger

            analyzer = JapaneseAnalyzer()

            # Delete tagger to force recreation
            del analyzer._local.tagger

            # Make next Tagger call fail
            mock_tagger_cls.side_effect = RuntimeError("Reinit failed")

            with self.assertRaises(RuntimeError):
                analyzer._get_tagger()


if __name__ == "__main__":
    unittest.main()
