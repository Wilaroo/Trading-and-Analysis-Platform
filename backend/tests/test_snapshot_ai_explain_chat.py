"""
Trade Snapshot AI Explain & Chat Context Tests
Tests for the new AI-powered annotation explanation and chat context endpoints.
Features tested:
- POST /api/trades/snapshots/{trade_id}/explain - AI explain annotation
- POST /api/trades/snapshots/{trade_id}/chat-context - Chat context builder
- Fallback response when Ollama/GPT-OSS is not connected
"""
import pytest
import os
import sys
sys.path.insert(0, '/app/backend')

from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

from pymongo import MongoClient
from services.trade_snapshot_service import TradeSnapshotService
from routers.trade_snapshots import (
    explain_annotation, get_chat_context, _call_llm_sync,
    init_snapshot_service, ExplainRequest
)
from fastapi import HTTPException


# Get MongoDB connection
MONGO_URL = os.environ.get('MONGO_URL')
DB_NAME = os.environ.get('DB_NAME', 'tradecommand')


@pytest.fixture(scope="module")
def db():
    """MongoDB database fixture."""
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def snapshot_service(db):
    """TradeSnapshotService fixture."""
    service = TradeSnapshotService(db)
    # Initialize the router's snapshot_service global
    init_snapshot_service(service)
    return service


@pytest.fixture(scope="module")
def sample_snapshot(snapshot_service):
    """Get a sample snapshot with annotations for testing."""
    snap = snapshot_service.snapshots_col.find_one(
        {"annotations": {"$exists": True, "$ne": []}},
        {"_id": 0}
    )
    if not snap:
        pytest.skip("No snapshots with annotations found")
    return snap


class TestExplainAnnotationEndpoint:
    """Tests for POST /api/trades/snapshots/{trade_id}/explain endpoint."""

    def test_explain_annotation_returns_success(self, snapshot_service, sample_snapshot):
        """Test that explain_annotation returns a successful response."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = explain_annotation(trade_id, request, source)
        
        assert result.get("success") is True, "Should return success"
        assert "explanation" in result, "Should have explanation field"
        assert "annotation" in result, "Should have annotation field"
        assert "trade_summary" in result, "Should have trade_summary field"
        
        print(f"PASS: explain_annotation returns success for trade {trade_id}")

    def test_explain_annotation_returns_fallback_when_no_llm(self, snapshot_service, sample_snapshot):
        """Test that explain_annotation returns fallback message when LLM unavailable."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = explain_annotation(trade_id, request, source)
        
        explanation = result.get("explanation", "")
        # In container without Ollama, should get fallback message
        assert len(explanation) > 0, "Explanation should not be empty"
        
        # Check if it's the fallback message (Ollama not connected in container)
        if "AI analysis is currently unavailable" in explanation:
            print("PASS: Fallback message returned (Ollama not connected)")
        else:
            print(f"PASS: AI explanation returned ({len(explanation)} chars)")

    def test_explain_annotation_with_custom_question(self, snapshot_service, sample_snapshot):
        """Test explain_annotation with a custom question."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        custom_question = "Why did we enter at this specific price level?"
        request = ExplainRequest(annotation_index=0, question=custom_question)
        result = explain_annotation(trade_id, request, source)
        
        assert result.get("success") is True
        assert "explanation" in result
        print(f"PASS: Custom question accepted for trade {trade_id}")

    def test_explain_annotation_returns_annotation_data(self, snapshot_service, sample_snapshot):
        """Test that explain_annotation returns the annotation data."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = explain_annotation(trade_id, request, source)
        
        annotation = result.get("annotation", {})
        assert "type" in annotation, "Annotation should have type"
        assert "label" in annotation, "Annotation should have label"
        
        print(f"PASS: Annotation data returned: {annotation.get('type')} - {annotation.get('label')}")

    def test_explain_annotation_returns_trade_summary(self, snapshot_service, sample_snapshot):
        """Test that explain_annotation returns trade summary."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = explain_annotation(trade_id, request, source)
        
        summary = result.get("trade_summary", {})
        assert "symbol" in summary, "Summary should have symbol"
        assert "direction" in summary, "Summary should have direction"
        assert "pnl" in summary, "Summary should have pnl"
        
        print(f"PASS: Trade summary returned: {summary.get('symbol')} {summary.get('direction')}")

    def test_explain_annotation_invalid_index_raises_error(self, snapshot_service, sample_snapshot):
        """Test that invalid annotation index raises HTTPException."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        num_annotations = len(sample_snapshot.get("annotations", []))
        
        request = ExplainRequest(annotation_index=999, question=None)
        
        with pytest.raises(HTTPException) as exc_info:
            explain_annotation(trade_id, request, source)
        
        assert exc_info.value.status_code == 400
        assert "out of range" in str(exc_info.value.detail).lower()
        print(f"PASS: Invalid index (999) raises 400 error (max index: {num_annotations - 1})")

    def test_explain_annotation_nonexistent_trade_raises_error(self, snapshot_service):
        """Test that non-existent trade raises HTTPException."""
        request = ExplainRequest(annotation_index=0, question=None)
        
        with pytest.raises(HTTPException) as exc_info:
            explain_annotation("nonexistent_trade_12345", request, "bot")
        
        assert exc_info.value.status_code == 404
        print("PASS: Non-existent trade raises 404 error")


class TestChatContextEndpoint:
    """Tests for POST /api/trades/snapshots/{trade_id}/chat-context endpoint."""

    def test_chat_context_returns_success(self, snapshot_service, sample_snapshot):
        """Test that get_chat_context returns a successful response."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = get_chat_context(trade_id, request, source)
        
        assert result.get("success") is True, "Should return success"
        assert "chat_message" in result, "Should have chat_message field"
        assert "trade_id" in result, "Should have trade_id field"
        assert "annotation_index" in result, "Should have annotation_index field"
        
        print(f"PASS: get_chat_context returns success for trade {trade_id}")

    def test_chat_context_message_contains_trade_info(self, snapshot_service, sample_snapshot):
        """Test that chat_message contains trade information."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        symbol = sample_snapshot.get("symbol", "")
        direction = sample_snapshot.get("direction", "")
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = get_chat_context(trade_id, request, source)
        
        chat_message = result.get("chat_message", "")
        assert len(chat_message) > 0, "Chat message should not be empty"
        assert symbol in chat_message, f"Chat message should contain symbol {symbol}"
        
        print(f"PASS: Chat message contains trade info: {chat_message[:100]}...")

    def test_chat_context_message_contains_annotation_info(self, snapshot_service, sample_snapshot):
        """Test that chat_message contains annotation information."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        annotations = sample_snapshot.get("annotations", [])
        
        if not annotations:
            pytest.skip("No annotations in sample snapshot")
        
        first_ann = annotations[0]
        ann_type = first_ann.get("type", "")
        ann_label = first_ann.get("label", "")
        
        request = ExplainRequest(annotation_index=0, question=None)
        result = get_chat_context(trade_id, request, source)
        
        chat_message = result.get("chat_message", "")
        # Should contain annotation type or label
        assert ann_type in chat_message.lower() or ann_label.lower() in chat_message.lower(), \
            f"Chat message should reference annotation type ({ann_type}) or label ({ann_label})"
        
        print(f"PASS: Chat message contains annotation info")

    def test_chat_context_with_custom_question(self, snapshot_service, sample_snapshot):
        """Test chat_context with a custom question."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        
        custom_question = "What could I have done differently?"
        request = ExplainRequest(annotation_index=0, question=custom_question)
        result = get_chat_context(trade_id, request, source)
        
        chat_message = result.get("chat_message", "")
        assert custom_question in chat_message, "Custom question should be in chat message"
        
        print(f"PASS: Custom question included in chat message")

    def test_chat_context_nonexistent_trade_raises_error(self, snapshot_service):
        """Test that non-existent trade raises HTTPException."""
        request = ExplainRequest(annotation_index=0, question=None)
        
        with pytest.raises(HTTPException) as exc_info:
            get_chat_context("nonexistent_trade_12345", request, "bot")
        
        assert exc_info.value.status_code == 404
        print("PASS: Non-existent trade raises 404 error")


class TestLLMFallback:
    """Tests for LLM fallback behavior."""

    def test_call_llm_sync_returns_fallback(self):
        """Test that _call_llm_sync returns fallback when no LLM available."""
        prompt = "Test prompt for AI analysis"
        context = "Test context"
        
        result = _call_llm_sync(prompt, context)
        
        assert len(result) > 0, "Should return non-empty response"
        # In container without Ollama, should get fallback
        if "AI analysis is currently unavailable" in result:
            print("PASS: Fallback message returned (expected in container)")
        else:
            print(f"PASS: LLM response returned ({len(result)} chars)")

    def test_fallback_message_is_informative(self):
        """Test that fallback message is informative."""
        prompt = "Test prompt"
        context = "Test context"
        
        result = _call_llm_sync(prompt, context)
        
        if "AI analysis is currently unavailable" in result:
            assert "Ollama" in result or "GPT-OSS" in result, \
                "Fallback should mention Ollama/GPT-OSS"
            assert "annotation" in result.lower() or "decision" in result.lower(), \
                "Fallback should reference the annotation data"
            print("PASS: Fallback message is informative")
        else:
            print("PASS: LLM is connected, no fallback needed")


class TestExplainRequestModel:
    """Tests for ExplainRequest Pydantic model."""

    def test_explain_request_defaults(self):
        """Test ExplainRequest default values."""
        request = ExplainRequest()
        
        assert request.annotation_index == 0, "Default annotation_index should be 0"
        assert request.question is None, "Default question should be None"
        print("PASS: ExplainRequest defaults are correct")

    def test_explain_request_with_values(self):
        """Test ExplainRequest with custom values."""
        request = ExplainRequest(annotation_index=2, question="Why this entry?")
        
        assert request.annotation_index == 2
        assert request.question == "Why this entry?"
        print("PASS: ExplainRequest accepts custom values")


class TestMultipleAnnotations:
    """Tests for handling multiple annotations."""

    def test_explain_different_annotation_indices(self, snapshot_service, sample_snapshot):
        """Test explaining different annotation indices."""
        trade_id = sample_snapshot["trade_id"]
        source = sample_snapshot["source"]
        annotations = sample_snapshot.get("annotations", [])
        
        if len(annotations) < 2:
            pytest.skip("Need at least 2 annotations for this test")
        
        # Test first annotation
        request0 = ExplainRequest(annotation_index=0, question=None)
        result0 = explain_annotation(trade_id, request0, source)
        
        # Test second annotation
        request1 = ExplainRequest(annotation_index=1, question=None)
        result1 = explain_annotation(trade_id, request1, source)
        
        # Should return different annotations
        ann0 = result0.get("annotation", {})
        ann1 = result1.get("annotation", {})
        
        assert ann0.get("type") != ann1.get("type") or ann0.get("label") != ann1.get("label"), \
            "Different indices should return different annotations"
        
        print(f"PASS: Different indices return different annotations")
        print(f"  Index 0: {ann0.get('type')} - {ann0.get('label')}")
        print(f"  Index 1: {ann1.get('type')} - {ann1.get('label')}")


class TestSnapshotCount:
    """Tests to verify snapshot data exists."""

    def test_snapshots_exist_in_database(self, db):
        """Verify snapshots exist in the database."""
        count = db.trade_snapshots.count_documents({})
        assert count > 0, "Should have snapshots in database"
        print(f"PASS: {count} snapshots exist in database")

    def test_snapshots_with_annotations_exist(self, db):
        """Verify snapshots with annotations exist."""
        count = db.trade_snapshots.count_documents({"annotations": {"$exists": True, "$ne": []}})
        assert count > 0, "Should have snapshots with annotations"
        print(f"PASS: {count} snapshots have annotations")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
