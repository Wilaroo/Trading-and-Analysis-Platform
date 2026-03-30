"""
Trade Snapshots API Tests
Tests for chart snapshot generation with AI annotations for trades.
"""
import pytest
import os
import sys
sys.path.insert(0, '/app/backend')

from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

from pymongo import MongoClient
from services.trade_snapshot_service import TradeSnapshotService


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
    return TradeSnapshotService(db)


class TestTradeSnapshotService:
    """Tests for TradeSnapshotService core functionality."""

    def test_get_existing_snapshot(self, snapshot_service):
        """Test retrieving an existing snapshot."""
        # Get any existing snapshot
        existing = snapshot_service.snapshots_col.find_one({}, {"trade_id": 1, "source": 1, "_id": 0})
        if not existing:
            pytest.skip("No existing snapshots to test")
        
        trade_id = existing["trade_id"]
        source = existing["source"]
        
        snap = snapshot_service.get_snapshot(trade_id, source)
        
        assert snap is not None, "Snapshot should be found"
        assert snap.get("trade_id") == trade_id
        assert snap.get("source") == source
        assert "symbol" in snap
        assert "chart_image" in snap
        assert "annotations" in snap
        assert isinstance(snap["annotations"], list)
        print(f"PASS: Retrieved snapshot for {snap.get('symbol')} trade {trade_id}")

    def test_get_nonexistent_snapshot(self, snapshot_service):
        """Test retrieving a non-existent snapshot returns None."""
        snap = snapshot_service.get_snapshot("nonexistent_trade_id_12345", "bot")
        assert snap is None, "Non-existent snapshot should return None"
        print("PASS: Non-existent snapshot returns None")

    def test_generate_snapshot_for_closed_trade(self, snapshot_service, db):
        """Test generating a snapshot for a closed trade."""
        # Find a closed bot trade
        closed_trade = db.bot_trades.find_one({"status": "closed"}, {"id": 1, "symbol": 1, "_id": 0})
        if not closed_trade:
            pytest.skip("No closed bot trades available")
        
        trade_id = closed_trade["id"]
        
        # Generate snapshot
        result = snapshot_service.generate_snapshot_sync(trade_id, "bot")
        
        assert result.get("success") is True, f"Generation should succeed: {result.get('error')}"
        assert "snapshot" in result
        assert result.get("has_chart") is True
        
        snap = result["snapshot"]
        assert snap.get("trade_id") == trade_id
        assert snap.get("symbol") == closed_trade["symbol"]
        assert "annotations" in snap
        print(f"PASS: Generated snapshot for {snap.get('symbol')} trade {trade_id}")

    def test_generate_snapshot_for_nonexistent_trade(self, snapshot_service):
        """Test generating snapshot for non-existent trade fails gracefully."""
        result = snapshot_service.generate_snapshot_sync("nonexistent_12345", "bot")
        
        assert result.get("success") is False
        assert "error" in result
        assert "not found" in result["error"].lower()
        print("PASS: Non-existent trade returns error")

    def test_snapshot_annotations_structure(self, snapshot_service, db):
        """Test that snapshot annotations have correct structure."""
        # Get a snapshot with annotations
        snap = snapshot_service.snapshots_col.find_one(
            {"annotations": {"$exists": True, "$ne": []}},
            {"_id": 0}
        )
        if not snap:
            pytest.skip("No snapshots with annotations found")
        
        annotations = snap.get("annotations", [])
        assert len(annotations) > 0, "Should have at least one annotation"
        
        for ann in annotations:
            assert "type" in ann, "Annotation should have type"
            assert ann["type"] in ["entry", "exit", "scale_out", "stop_adjust", "gate_decision"]
            assert "label" in ann, "Annotation should have label"
            assert "reasons" in ann, "Annotation should have reasons list"
            assert isinstance(ann["reasons"], list)
        
        print(f"PASS: Annotations structure valid ({len(annotations)} annotations)")

    def test_snapshot_chart_image_is_base64(self, snapshot_service):
        """Test that chart_image is valid base64."""
        import base64
        
        snap = snapshot_service.snapshots_col.find_one(
            {"chart_image": {"$exists": True, "$ne": ""}},
            {"_id": 0, "chart_image": 1, "trade_id": 1}
        )
        if not snap:
            pytest.skip("No snapshots with chart images found")
        
        chart_image = snap.get("chart_image", "")
        assert len(chart_image) > 0, "Chart image should not be empty"
        
        # Verify it's valid base64
        try:
            decoded = base64.b64decode(chart_image)
            assert len(decoded) > 0
            # Check PNG magic bytes
            assert decoded[:4] == b'\x89PNG', "Should be a PNG image"
        except Exception as e:
            pytest.fail(f"Chart image is not valid base64 PNG: {e}")
        
        print(f"PASS: Chart image is valid base64 PNG ({len(chart_image)} chars)")

    def test_batch_generate_sync(self, snapshot_service):
        """Test batch generation of snapshots."""
        result = snapshot_service.batch_generate_sync(limit=2)
        
        assert "generated" in result
        assert "errors" in result
        assert isinstance(result["generated"], int)
        assert isinstance(result["errors"], int)
        
        print(f"PASS: Batch generate - {result['generated']} generated, {result['errors']} errors")

    def test_snapshot_metadata_fields(self, snapshot_service):
        """Test that snapshot has all required metadata fields."""
        snap = snapshot_service.snapshots_col.find_one({}, {"_id": 0})
        if not snap:
            pytest.skip("No snapshots available")
        
        required_fields = [
            "trade_id", "source", "symbol", "direction", "entry_price",
            "exit_price", "pnl", "entry_time", "exit_time", "timeframe",
            "chart_image", "annotations", "generated_at"
        ]
        
        for field in required_fields:
            assert field in snap, f"Missing required field: {field}"
        
        print(f"PASS: All required metadata fields present")


class TestSnapshotAnnotationTypes:
    """Tests for different annotation types in snapshots."""

    def test_entry_annotation_exists(self, snapshot_service):
        """Test that snapshots have entry annotations."""
        snap = snapshot_service.snapshots_col.find_one(
            {"annotations.type": "entry"},
            {"_id": 0, "annotations": 1, "trade_id": 1}
        )
        if not snap:
            pytest.skip("No snapshots with entry annotations")
        
        entry_anns = [a for a in snap["annotations"] if a["type"] == "entry"]
        assert len(entry_anns) > 0
        
        entry = entry_anns[0]
        assert entry.get("label") == "ENTRY"
        assert "price" in entry
        assert "color" in entry
        print("PASS: Entry annotation structure valid")

    def test_exit_annotation_exists(self, snapshot_service):
        """Test that snapshots have exit annotations."""
        snap = snapshot_service.snapshots_col.find_one(
            {"annotations.type": "exit"},
            {"_id": 0, "annotations": 1, "trade_id": 1}
        )
        if not snap:
            pytest.skip("No snapshots with exit annotations")
        
        exit_anns = [a for a in snap["annotations"] if a["type"] == "exit"]
        assert len(exit_anns) > 0
        
        exit_ann = exit_anns[0]
        assert exit_ann.get("label") == "EXIT"
        assert "price" in exit_ann
        assert "reasons" in exit_ann
        print("PASS: Exit annotation structure valid")


class TestSnapshotEdgeCases:
    """Tests for edge cases in snapshot generation."""

    def test_snapshot_with_none_exit_price(self, snapshot_service, db):
        """Test snapshot generation handles None exit_price."""
        # Find a trade with None exit_price
        trade = db.bot_trades.find_one(
            {"status": "closed", "exit_price": None},
            {"id": 1, "symbol": 1, "_id": 0}
        )
        if not trade:
            pytest.skip("No closed trades with None exit_price")
        
        result = snapshot_service.generate_snapshot_sync(trade["id"], "bot")
        
        # Should not crash, should succeed
        assert result.get("success") is True, f"Should handle None exit_price: {result.get('error')}"
        print(f"PASS: Handled None exit_price for {trade['symbol']}")

    def test_snapshot_with_zero_pnl(self, snapshot_service, db):
        """Test snapshot generation handles zero PnL."""
        trade = db.bot_trades.find_one(
            {"status": "closed", "realized_pnl": 0},
            {"id": 1, "symbol": 1, "_id": 0}
        )
        if not trade:
            pytest.skip("No closed trades with zero PnL")
        
        result = snapshot_service.generate_snapshot_sync(trade["id"], "bot")
        
        assert result.get("success") is True
        print(f"PASS: Handled zero PnL for {trade['symbol']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
