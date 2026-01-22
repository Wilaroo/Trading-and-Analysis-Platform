"""
Test Suite for Catalyst Scoring System and Trade Templates
Tests the new features: Catalyst Scoring API and Trade Templates API
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestCatalystScoringAPI:
    """Tests for Catalyst Scoring System - POST /api/catalyst/score/quick and GET /api/catalyst/score-guide"""
    
    def test_score_guide_endpoint(self):
        """Test GET /api/catalyst/score-guide returns scoring rubric"""
        response = requests.get(f"{BASE_URL}/api/catalyst/score-guide")
        assert response.status_code == 200
        
        data = response.json()
        # Verify scale structure
        assert "scale" in data
        assert "ratings" in data["scale"]
        assert "A+" in data["scale"]["ratings"]
        assert "B+" in data["scale"]["ratings"]
        assert "C" in data["scale"]["ratings"]
        assert "D" in data["scale"]["ratings"]
        assert "F" in data["scale"]["ratings"]
        
        # Verify A+ rating details
        a_plus = data["scale"]["ratings"]["A+"]
        assert a_plus["range"] == [8, 10]
        assert a_plus["bias"] == "STRONG_LONG"
        
        # Verify earnings components
        assert "earnings_components" in data
        assert "revenue" in data["earnings_components"]
        assert "eps" in data["earnings_components"]
        assert "margins" in data["earnings_components"]
        assert "guidance" in data["earnings_components"]
        assert "tape" in data["earnings_components"]
        
        print("✓ Score guide endpoint returns complete scoring rubric")
    
    def test_quick_score_positive_catalyst(self):
        """Test POST /api/catalyst/score/quick with positive earnings data"""
        payload = {
            "symbol": "AAPL",
            "eps_beat_pct": 5.0,
            "revenue_beat_pct": 3.0,
            "guidance": "raised",
            "price_reaction_pct": 4.0,
            "volume_multiple": 2.5
        }
        
        response = requests.post(
            f"{BASE_URL}/api/catalyst/score/quick",
            json=payload
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["catalyst_type"] == "EARNINGS"
        assert data["raw_score"] >= 4  # Should be positive
        assert data["rating"] in ["A+", "B+"]
        assert data["bias"] in ["STRONG_LONG", "LONG"]
        
        # Verify components
        assert "components" in data
        assert "eps_beat" in data["components"]
        assert "revenue_beat" in data["components"]
        assert "guidance" in data["components"]
        assert "tape_reaction" in data["components"]
        
        print(f"✓ Quick score positive catalyst: {data['rating']} ({data['raw_score']})")
    
    def test_quick_score_negative_catalyst(self):
        """Test POST /api/catalyst/score/quick with negative earnings data"""
        payload = {
            "symbol": "TSLA",
            "eps_beat_pct": -5.0,
            "revenue_beat_pct": -3.0,
            "guidance": "cut",
            "price_reaction_pct": -8.0,
            "volume_multiple": 3.0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/catalyst/score/quick",
            json=payload
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["symbol"] == "TSLA"
        assert data["raw_score"] <= -4  # Should be negative
        assert data["rating"] in ["D", "F"]
        assert data["bias"] in ["SHORT", "STRONG_SHORT"]
        
        print(f"✓ Quick score negative catalyst: {data['rating']} ({data['raw_score']})")
    
    def test_quick_score_neutral_catalyst(self):
        """Test POST /api/catalyst/score/quick with neutral earnings data"""
        payload = {
            "symbol": "MSFT",
            "eps_beat_pct": 0.5,
            "revenue_beat_pct": 0.5,
            "guidance": "inline",
            "price_reaction_pct": 0.5,
            "volume_multiple": 1.0
        }
        
        response = requests.post(
            f"{BASE_URL}/api/catalyst/score/quick",
            json=payload
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["symbol"] == "MSFT"
        assert -3 <= data["raw_score"] <= 3  # Should be neutral range
        assert data["rating"] == "C"
        assert data["bias"] == "NEUTRAL"
        
        print(f"✓ Quick score neutral catalyst: {data['rating']} ({data['raw_score']})")
    
    def test_quick_score_score_range(self):
        """Test that scores are properly bounded between -10 and +10"""
        # Extreme positive
        payload = {
            "symbol": "TEST",
            "eps_beat_pct": 20.0,
            "revenue_beat_pct": 20.0,
            "guidance": "raised",
            "price_reaction_pct": 15.0,
            "volume_multiple": 5.0
        }
        
        response = requests.post(f"{BASE_URL}/api/catalyst/score/quick", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert -10 <= data["raw_score"] <= 10
        
        # Extreme negative
        payload["eps_beat_pct"] = -20.0
        payload["revenue_beat_pct"] = -20.0
        payload["guidance"] = "cut"
        payload["price_reaction_pct"] = -15.0
        
        response = requests.post(f"{BASE_URL}/api/catalyst/score/quick", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert -10 <= data["raw_score"] <= 10
        
        print("✓ Score range properly bounded between -10 and +10")


class TestTradeTemplatesAPI:
    """Tests for Trade Templates - GET /api/trades/templates/defaults and /api/trades/templates/list"""
    
    def test_default_templates_endpoint(self):
        """Test GET /api/trades/templates/defaults returns system templates"""
        response = requests.get(f"{BASE_URL}/api/trades/templates/defaults")
        assert response.status_code == 200
        
        data = response.json()
        assert "templates" in data
        assert "count" in data
        assert data["count"] == 8  # 2 basic + 6 strategy templates
        
        templates = data["templates"]
        
        # Verify basic templates exist
        basic_templates = [t for t in templates if t["template_type"] == "basic"]
        assert len(basic_templates) == 2
        
        # Verify Quick Long template
        quick_long = next((t for t in templates if t["name"] == "Quick Long"), None)
        assert quick_long is not None
        assert quick_long["direction"] == "long"
        assert quick_long["is_system"] == True
        
        # Verify Quick Short template
        quick_short = next((t for t in templates if t["name"] == "Quick Short"), None)
        assert quick_short is not None
        assert quick_short["direction"] == "short"
        
        print(f"✓ Default templates endpoint returns {data['count']} templates")
    
    def test_templates_list_endpoint(self):
        """Test GET /api/trades/templates/list returns all templates"""
        response = requests.get(f"{BASE_URL}/api/trades/templates/list")
        assert response.status_code == 200
        
        data = response.json()
        assert "templates" in data
        assert "user_count" in data
        assert "default_count" in data
        assert data["default_count"] == 8
        
        print(f"✓ Templates list endpoint returns {data['default_count']} default templates")
    
    def test_strategy_templates_structure(self):
        """Test that strategy templates have correct structure"""
        response = requests.get(f"{BASE_URL}/api/trades/templates/defaults")
        assert response.status_code == 200
        
        templates = response.json()["templates"]
        strategy_templates = [t for t in templates if t["template_type"] == "strategy"]
        
        assert len(strategy_templates) == 6
        
        # Verify each strategy template has required fields
        for template in strategy_templates:
            assert "strategy_id" in template
            assert "strategy_name" in template
            assert "market_context" in template
            assert "direction" in template
            assert "default_shares" in template
            assert "risk_percent" in template
            assert "reward_ratio" in template
            assert template["strategy_id"] != ""  # Strategy templates must have strategy_id
        
        # Verify specific templates
        trend_momentum = next((t for t in strategy_templates if t["strategy_id"] == "INT-01"), None)
        assert trend_momentum is not None
        assert trend_momentum["market_context"] == "TRENDING"
        
        mean_reversion = next((t for t in strategy_templates if t["strategy_id"] == "INT-07"), None)
        assert mean_reversion is not None
        assert mean_reversion["market_context"] == "MEAN_REVERSION"
        
        print("✓ Strategy templates have correct structure and market contexts")
    
    def test_template_risk_reward_values(self):
        """Test that templates have valid risk/reward values"""
        response = requests.get(f"{BASE_URL}/api/trades/templates/defaults")
        assert response.status_code == 200
        
        templates = response.json()["templates"]
        
        for template in templates:
            assert 0 < template["risk_percent"] <= 5  # Risk should be 0-5%
            assert 1 <= template["reward_ratio"] <= 5  # R:R should be 1:1 to 5:1
            assert template["default_shares"] > 0
        
        print("✓ All templates have valid risk/reward values")


class TestTradeCreationWithTemplate:
    """Tests for creating trades using templates"""
    
    def test_create_trade_basic(self):
        """Test POST /api/trades creates a trade"""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": "INT-01",
            "strategy_name": "Test Strategy",
            "entry_price": 150.00,
            "shares": 100,
            "direction": "long",
            "market_context": "TRENDING",
            "stop_loss": 145.00,
            "take_profit": 160.00,
            "notes": "Test trade from pytest"
        }
        
        response = requests.post(f"{BASE_URL}/api/trades", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["symbol"] == payload["symbol"].upper()
        assert data["strategy_id"] == "INT-01"
        assert data["entry_price"] == 150.00
        assert data["shares"] == 100
        assert data["direction"] == "long"
        assert data["status"] == "open"
        assert "id" in data
        
        # Cleanup - delete the test trade
        trade_id = data["id"]
        delete_response = requests.delete(f"{BASE_URL}/api/trades/{trade_id}")
        assert delete_response.status_code == 200
        
        print(f"✓ Trade created and deleted successfully: {payload['symbol']}")
    
    def test_create_trade_from_template(self):
        """Test POST /api/trades/from-template creates trade with template defaults"""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "template_id": None,  # Using default template
            "symbol": f"TEST_{unique_id}",
            "entry_price": 200.00,
            "shares": 50,
            "direction": "long"
        }
        
        response = requests.post(f"{BASE_URL}/api/trades/from-template", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["symbol"] == payload["symbol"].upper()
        assert data["entry_price"] == 200.00
        assert "id" in data
        
        # Cleanup
        trade_id = data["id"]
        requests.delete(f"{BASE_URL}/api/trades/{trade_id}")
        
        print(f"✓ Trade from template created successfully: {payload['symbol']}")


class TestCatalystHistoryAndRecent:
    """Tests for catalyst history endpoints"""
    
    def test_recent_catalysts_endpoint(self):
        """Test GET /api/catalyst/recent returns recent catalysts"""
        response = requests.get(f"{BASE_URL}/api/catalyst/recent")
        assert response.status_code == 200
        
        data = response.json()
        assert "catalysts" in data
        assert "count" in data
        
        print(f"✓ Recent catalysts endpoint returns {data['count']} catalysts")
    
    def test_catalyst_history_endpoint(self):
        """Test GET /api/catalyst/history/{symbol} returns catalyst history"""
        response = requests.get(f"{BASE_URL}/api/catalyst/history/AAPL")
        assert response.status_code == 200
        
        data = response.json()
        assert "symbol" in data
        assert data["symbol"] == "AAPL"
        assert "catalysts" in data
        assert "count" in data
        
        print(f"✓ Catalyst history endpoint returns {data['count']} catalysts for AAPL")


class TestTradeJournalIntegration:
    """Integration tests for Trade Journal with templates"""
    
    def test_full_trade_workflow_with_template(self):
        """Test complete workflow: get templates -> create trade -> close trade"""
        # Step 1: Get templates
        templates_response = requests.get(f"{BASE_URL}/api/trades/templates/list")
        assert templates_response.status_code == 200
        templates = templates_response.json()["templates"]
        assert len(templates) > 0
        
        # Step 2: Create trade using template values
        unique_id = str(uuid.uuid4())[:8]
        template = templates[0]  # Use first template
        
        trade_payload = {
            "symbol": f"TEST_{unique_id}",
            "strategy_id": template.get("strategy_id", "MANUAL"),
            "strategy_name": template.get("strategy_name", "Manual Trade"),
            "entry_price": 100.00,
            "shares": template.get("default_shares", 100),
            "direction": template.get("direction", "long"),
            "market_context": template.get("market_context", ""),
            "stop_loss": 98.00,
            "take_profit": 104.00,
            "notes": f"Test trade using template: {template['name']}"
        }
        
        create_response = requests.post(f"{BASE_URL}/api/trades", json=trade_payload)
        assert create_response.status_code == 200
        trade = create_response.json()
        trade_id = trade["id"]
        
        # Step 3: Verify trade was created
        get_response = requests.get(f"{BASE_URL}/api/trades/{trade_id}")
        assert get_response.status_code == 200
        fetched_trade = get_response.json()
        assert fetched_trade["symbol"] == trade_payload["symbol"].upper()
        assert fetched_trade["status"] == "open"
        
        # Step 4: Close the trade
        close_response = requests.post(
            f"{BASE_URL}/api/trades/{trade_id}/close",
            json={"exit_price": 105.00, "notes": "Test close"}
        )
        assert close_response.status_code == 200
        closed_trade = close_response.json()
        assert closed_trade["status"] == "closed"
        assert closed_trade["pnl"] > 0  # Should be profitable
        
        print(f"✓ Full trade workflow completed: {trade_payload['symbol']} - P&L: ${closed_trade['pnl']:.2f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
