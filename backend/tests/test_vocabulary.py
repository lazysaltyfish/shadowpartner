"""Tests for vocabulary feature.

This module tests:
1. CRUD operations for vocabulary items
2. API endpoints for vocabulary retrieval
3. VocabularyAnalyzer service functions
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from db import get_session
from db.crud import (
    create_vocabulary_items,
    delete_vocabulary_by_asset,
    get_vocabulary_by_asset,
    get_vocabulary_stats,
)
from db.engine import SessionLocal
from db.models import Asset, AssetType
from main import create_app
from services.vocabulary_analyzer import VocabularyAnalyzer

# ==================== Fixtures ====================


@pytest.fixture(scope="function")
def client():
    """Create a test client for API tests."""
    app = create_app()
    client = TestClient(app)

    def override_get_session():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session

    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def test_asset_with_vocabulary(db_session):
    """Create an asset with vocabulary items for testing."""
    # Create asset
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_video_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    # Create vocabulary items
    vocab_data = [
        {
            "word": "承諾",
            "surface_form": "承諾された",
            "reading": "しょうだく",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "承诺",
            "meaning_en": "consent",
            "learning_note": "Formal expression",
            "start_time": 260.0,
            "end_time": 265.0,
            "original_sentence": "承諾されたそうです。",
        },
        {
            "word": "耳を疑う",
            "surface_form": "耳を疑いました",
            "reading": "みみをうたがう",
            "jlpt_level": "N2",
            "part_of_speech": "Idiom",
            "meaning_cn": "难以置信",
            "meaning_en": "disbelieve",
            "learning_note": "Idiom meaning",
            "start_time": 265.0,
            "end_time": 270.0,
            "original_sentence": "耳を疑いました。",
        },
        {
            "word": "根回し",
            "surface_form": "根回し",
            "reading": "ねまわし",
            "jlpt_level": "Business",
            "part_of_speech": "Noun",
            "meaning_cn": "事前疏通",
            "meaning_en": "preparation",
            "learning_note": "Business term",
            "start_time": 270.0,
            "end_time": 275.0,
            "original_sentence": "根回しが重要です。",
        },
        {
            "word": "食べる",
            "surface_form": "食べました",
            "reading": "たべる",
            "jlpt_level": "N5",
            "part_of_speech": "Verb",
            "meaning_cn": "吃",
            "meaning_en": "to eat",
            "learning_note": "Basic verb",
            "start_time": 280.0,
            "end_time": 285.0,
            "original_sentence": "ご飯を食べました。",
        },
    ]

    items = create_vocabulary_items(db_session, asset.id, vocab_data)
    db_session.commit()
    db_session.refresh(asset)

    return asset.id, items


# ==================== CRUD Tests ====================


def test_create_vocabulary_items(db_session):
    """Test creating vocabulary items for an asset."""
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    vocab_data = [
        {
            "word": "承諾",
            "surface_form": "承諾された",
            "reading": "しょうだく",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "承诺",
            "meaning_en": "consent",
            "learning_note": "Formal",
            "start_time": 100.0,
            "end_time": 105.0,
            "original_sentence": "承諾された。",
        },
    ]

    items = create_vocabulary_items(db_session, asset.id, vocab_data)

    assert len(items) == 1
    assert items[0].word == "承諾"
    assert items[0].surface_form == "承諾された"
    assert items[0].reading == "しょうだく"
    assert items[0].jlpt_level == "N1"
    assert items[0].start_time == 100.0
    assert items[0].end_time == 105.0


def test_create_vocabulary_fallback_surface_form(db_session):
    """Test surface_form falls back to word when not provided."""
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    vocab_data = [
        {
            "word": "根回し",
            # surface_form not provided - should fallback to word
            "reading": "ねまわし",
            "jlpt_level": "Business",
            "part_of_speech": "Noun",
            "meaning_cn": "疏通",
            "start_time": 100.0,
            "end_time": 105.0,
            "original_sentence": "根回し",
        },
    ]

    items = create_vocabulary_items(db_session, asset.id, vocab_data)

    assert len(items) == 1
    assert items[0].surface_form == "根回し"  # Should fall back to word


def test_get_vocabulary_by_asset(test_asset_with_vocabulary, db_session):
    """Test retrieving vocabulary items for an asset."""
    asset_id, items = test_asset_with_vocabulary

    vocab_items = get_vocabulary_by_asset(db_session, asset_id)

    assert len(vocab_items) == 4
    assert vocab_items[0].word == "承諾"
    assert vocab_items[1].word == "耳を疑う"
    assert vocab_items[2].word == "根回し"
    assert vocab_items[3].word == "食べる"


def test_get_vocabulary_by_asset_orders_by_start_time(db_session):
    """Test vocabulary items are ordered by start_time."""
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    # Add items in random order
    vocab_data = [
        {
            "word": "Third",
            "surface_form": "Third",
            "reading": "third",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "第三",
            "start_time": 300.0,
            "end_time": 305.0,
            "original_sentence": "Third",
        },
        {
            "word": "First",
            "surface_form": "First",
            "reading": "first",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "第一",
            "start_time": 100.0,
            "end_time": 105.0,
            "original_sentence": "First",
        },
        {
            "word": "Second",
            "surface_form": "Second",
            "reading": "second",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "第二",
            "start_time": 200.0,
            "end_time": 205.0,
            "original_sentence": "Second",
        },
    ]

    create_vocabulary_items(db_session, asset.id, vocab_data)

    vocab_items = get_vocabulary_by_asset(db_session, asset.id)

    assert [v.word for v in vocab_items] == ["First", "Second", "Third"]


def test_get_vocabulary_empty_for_nonexistent_asset(db_session):
    """Test retrieving vocabulary for non-existent asset returns empty list."""
    fake_id = uuid.uuid4()
    vocab_items = get_vocabulary_by_asset(db_session, fake_id)
    assert vocab_items == []


def test_get_vocabulary_stats(test_asset_with_vocabulary, db_session):
    """Test retrieving vocabulary statistics."""
    asset_id, _ = test_asset_with_vocabulary

    stats = get_vocabulary_stats(db_session, asset_id)

    assert stats["N1"] == 1
    assert stats["N2"] == 1
    assert stats["N5"] == 1
    assert stats["Business"] == 1
    assert stats["N3"] == 0
    assert stats["N4"] == 0
    assert stats["Other"] == 0


def test_get_vocabulary_stats_unknown_level(db_session):
    """Test vocabulary stats handle unknown JLPT levels."""
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    vocab_data = [
        {
            "word": "Unknown",
            "surface_form": "Unknown",
            "reading": "unknown",
            "jlpt_level": None,  # No level specified
            "part_of_speech": "Noun",
            "meaning_cn": "未知",
            "start_time": 100.0,
            "end_time": 105.0,
            "original_sentence": "Unknown",
        },
    ]

    create_vocabulary_items(db_session, asset.id, vocab_data)

    stats = get_vocabulary_stats(db_session, asset.id)

    assert stats["Other"] == 1


def test_delete_vocabulary_by_asset(test_asset_with_vocabulary, db_session):
    """Test deleting all vocabulary items for an asset."""
    asset_id, _ = test_asset_with_vocabulary

    # Verify items exist
    items_before = get_vocabulary_by_asset(db_session, asset_id)
    assert len(items_before) == 4

    # Delete vocabulary
    count = delete_vocabulary_by_asset(db_session, asset_id)
    assert count == 4

    # Verify items are deleted
    items_after = get_vocabulary_by_asset(db_session, asset_id)
    assert len(items_after) == 0


def test_delete_vocabulary_nonexistent_asset(db_session):
    """Test deleting vocabulary for non-existent asset returns 0."""
    fake_id = uuid.uuid4()
    count = delete_vocabulary_by_asset(db_session, fake_id)
    assert count == 0


# ==================== API Tests ====================


def test_get_vocabulary_api_success(client, test_asset_with_vocabulary):
    """Test GET /api/assets/{asset_id}/vocabulary returns vocabulary items."""
    asset_id, _ = test_asset_with_vocabulary

    response = client.get(f"/api/assets/{asset_id}/vocabulary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 4
    assert len(data["items"]) == 4
    assert "stats" in data

    # Check first item
    first_item = data["items"][0]
    assert first_item["word"] == "承諾"
    assert first_item["surface_form"] == "承諾された"
    assert first_item["reading"] == "しょうだく"
    assert first_item["jlpt_level"] == "N1"
    assert first_item["start_time"] == 260.0


def test_get_vocabulary_api_nonexistent_asset(client):
    """Test GET /api/assets/{asset_id}/vocabulary returns 404 for non-existent asset."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/assets/{fake_id}/vocabulary")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_vocabulary_api_invalid_asset_id(client):
    """Test GET /api/assets/{asset_id}/vocabulary returns 400 for invalid asset ID."""
    response = client.get("/api/assets/not-a-uuid/vocabulary")

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_get_vocabulary_api_includes_stats(client, test_asset_with_vocabulary):
    """Test vocabulary API response includes statistics."""
    asset_id, _ = test_asset_with_vocabulary

    response = client.get(f"/api/assets/{asset_id}/vocabulary")

    assert response.status_code == 200
    data = response.json()
    stats = data["stats"]

    assert stats["N1"] == 1
    assert stats["N2"] == 1
    assert stats["Business"] == 1
    assert stats["N5"] == 1


def test_get_vocabulary_api_empty_asset(client, db_session):
    """Test vocabulary API for asset with no vocabulary items."""
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    response = client.get(f"/api/assets/{asset.id}/vocabulary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 0
    assert data["items"] == []
    assert data["stats"] == {
        "N1": 0,
        "N2": 0,
        "N3": 0,
        "N4": 0,
        "N5": 0,
        "Business": 0,
        "Other": 0,
    }


# ==================== VocabularyAnalyzer Service Tests ====================


class TestVocabularyAnalyzerTimestampParsing:
    """Test timestamp parsing in VocabularyAnalyzer."""

    def test_parse_timestamp_mm_ss_format(self):
        """Test parsing MM:SS format."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("04:20") == 260.0
        assert analyzer._parse_timestamp("00:30") == 30.0
        assert analyzer._parse_timestamp("10:00") == 600.0

    def test_parse_timestamp_single_digit_minutes(self):
        """Test parsing M:SS format (single digit minutes)."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("4:20") == 260.0
        assert analyzer._parse_timestamp("0:30") == 30.0

    def test_parse_timestamp_with_decimal_seconds(self):
        """Test parsing MM:SS.sss format with milliseconds."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("04:20.5") == 260.5
        assert analyzer._parse_timestamp("04:20.123") == 260.123
        assert analyzer._parse_timestamp("0:30.5") == 30.5

    def test_parse_timestamp_hh_mm_ss_format(self):
        """Test parsing HH:MM:SS format."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("01:04:20") == 3860.0
        assert analyzer._parse_timestamp("00:10:30") == 630.0

    def test_parse_timestamp_hh_mm_ss_with_decimal(self):
        """Test parsing HH:MM:SS.sss format."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("01:04:20.5") == 3860.5

    def test_parse_timestamp_invalid_format(self):
        """Test parsing invalid timestamp returns 0.0."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp("invalid") == 0.0
        assert analyzer._parse_timestamp("") == 0.0
        assert analyzer._parse_timestamp("abc:def") == 0.0

    def test_parse_timestamp_with_whitespace(self):
        """Test parsing timestamp with surrounding whitespace."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_timestamp(" 04:20 ") == 260.0
        assert analyzer._parse_timestamp("\t4:20\n") == 260.0


class TestVocabularyAnalyzerJsonParsing:
    """Test JSON response parsing in VocabularyAnalyzer."""

    def test_parse_valid_json_array(self):
        """Test parsing valid JSON array."""
        analyzer = VocabularyAnalyzer()
        json_str = '[{"word": "test", "reading": "てすと"}]'
        result = analyzer._parse_json_response(json_str)
        assert len(result) == 1
        assert result[0]["word"] == "test"

    def test_parse_json_from_markdown_code_block(self):
        """Test extracting JSON from markdown code block."""
        analyzer = VocabularyAnalyzer()
        json_str = '```json\n[{"word": "test", "reading": "てすと"}]\n```'
        result = analyzer._parse_json_response(json_str)
        assert len(result) == 1
        assert result[0]["word"] == "test"

    def test_parse_json_from_markdown_without_json_keyword(self):
        """Test extracting JSON from markdown without json keyword."""
        analyzer = VocabularyAnalyzer()
        json_str = '```\n[{"word": "test", "reading": "てすと"}]\n```'
        result = analyzer._parse_json_response(json_str)
        assert len(result) == 1
        assert result[0]["word"] == "test"

    def test_parse_json_with_conversational_text(self):
        """Test extracting JSON from response with conversational text."""
        analyzer = VocabularyAnalyzer()
        json_str = 'Here is the result:\n[{"word": "test", "reading": "てすと"}]\nHope this helps!'
        result = analyzer._parse_json_response(json_str)
        assert len(result) == 1
        assert result[0]["word"] == "test"

    def test_parse_invalid_json_returns_empty_list(self):
        """Test that invalid JSON returns empty list."""
        analyzer = VocabularyAnalyzer()
        assert analyzer._parse_json_response("not json") == []
        assert analyzer._parse_json_response("{invalid json}") == []


class TestVocabularyAnalyzerSubtitleFormatting:
    """Test subtitle formatting for the prompt."""

    def test_format_subtitles_with_text(self):
        """Test formatting subtitles with text field."""
        analyzer = VocabularyAnalyzer()
        segments = [
            {"start": 60.0, "end": 65.0, "text": "こんにちは"},
            {"start": 125.0, "end": 130.0, "text": "さようなら"},
        ]
        result = analyzer._format_subtitles(segments)
        assert "[01:00] こんにちは" in result
        assert "[02:05] さようなら" in result

    def test_format_subtitles_with_words(self):
        """Test formatting subtitles with words field (word-level segments)."""
        analyzer = VocabularyAnalyzer()
        segments = [
            {
                "start": 60.0,
                "end": 65.0,
                "words": [{"text": "こんにちは"}, {"text": "世界"}],
            }
        ]
        result = analyzer._format_subtitles(segments)
        assert "[01:00]" in result
        assert "こんにちは世界" in result

    def test_format_subtitles_empty_segments(self):
        """Test formatting with empty segments list."""
        analyzer = VocabularyAnalyzer()
        result = analyzer._format_subtitles([])
        assert result == ""

    def test_format_subtitles_timestamp_format(self):
        """Test that timestamps are formatted as MM:SS with leading zeros."""
        analyzer = VocabularyAnalyzer()
        segments = [
            {"start": 0.0, "text": "Start"},
            {"start": 65.0, "text": "After minute"},
        ]
        result = analyzer._format_subtitles(segments)
        assert "[00:00]" in result
        assert "[01:05]" in result


# ==================== Integration Tests ====================


def test_vocabulary_deleted_when_asset_deleted(db_session):
    """Test that vocabulary items are cascade deleted when asset is deleted."""
    from db.crud import delete_asset

    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(asset)
    db_session.flush()

    vocab_data = [
        {
            "word": "Test",
            "surface_form": "Test",
            "reading": "てすと",
            "jlpt_level": "N1",
            "part_of_speech": "Noun",
            "meaning_cn": "测试",
            "start_time": 100.0,
            "end_time": 105.0,
            "original_sentence": "Test",
        }
    ]
    create_vocabulary_items(db_session, asset.id, vocab_data)
    db_session.commit()

    # Verify vocabulary exists
    items_before = get_vocabulary_by_asset(db_session, asset.id)
    assert len(items_before) == 1

    # Delete asset
    import asyncio

    asyncio.run(delete_asset(db_session, asset.id))

    # Verify vocabulary is deleted
    items_after = get_vocabulary_by_asset(db_session, asset.id)
    assert len(items_after) == 0
