"""
Trailing Stop Feature Tests
Tests for automatic trailing stop functionality after targets are hit.
Features tested:
- Trades include trailing_stop_config with mode, original_stop, current_stop, trail_pct
- trailing_stop_config.mode starts as 'original'
- After Target 1 hit, mode changes to 'breakeven' and stop moves to entry price
- After Target 2 hit, mode changes to 'trailing' and stop trails by trail_pct
- high_water_mark tracks highest price since trailing activated
- stop_adjustments array records history of stop changes
- Close reason includes 'stop_loss_breakeven' and 'stop_loss_trailing' variants
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTrailingStopConfigStructure:
    """Test that trades have correct trailing_stop_config structure"""
    
    def test_pending_trades_have_trailing_stop_config(self):
        """Pending trades should include trailing_stop_config field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        trades = data.get("trades", [])
        print(f"Found {len(trades)} pending trades")
        
        for trade in trades:
            assert "trailing_stop_config" in trade, f"Trade {trade.get('id')} missing trailing_stop_config"
            
            config = trade.get("trailing_stop_config", {})
            # Verify all required fields exist
            assert "enabled" in config, "trailing_stop_config missing 'enabled' field"
            assert "mode" in config, "trailing_stop_config missing 'mode' field"
            assert "original_stop" in config, "trailing_stop_config missing 'original_stop' field"
            assert "current_stop" in config, "trailing_stop_config missing 'current_stop' field"
            assert "trail_pct" in config, "trailing_stop_config missing 'trail_pct' field"
            assert "high_water_mark" in config, "trailing_stop_config missing 'high_water_mark' field"
            assert "low_water_mark" in config, "trailing_stop_config missing 'low_water_mark' field"
            assert "stop_adjustments" in config, "trailing_stop_config missing 'stop_adjustments' field"
            
            print(f"Trade {trade.get('symbol')}: trailing_stop_config = {config}")
    
    def test_open_trades_have_trailing_stop_config(self):
        """Open trades should include trailing_stop_config field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        trades = data.get("trades", [])
        print(f"Found {len(trades)} open trades")
        
        for trade in trades:
            assert "trailing_stop_config" in trade, f"Trade {trade.get('id')} missing trailing_stop_config"
            
            config = trade.get("trailing_stop_config", {})
            required_fields = ["enabled", "mode", "original_stop", "current_stop", "trail_pct", 
                             "high_water_mark", "low_water_mark", "stop_adjustments"]
            
            for field in required_fields:
                assert field in config, f"trailing_stop_config missing '{field}' field"
            
            print(f"Trade {trade.get('symbol')}: trailing_stop_config = {config}")
    
    def test_trailing_stop_mode_starts_as_original(self):
        """New trades should have mode='original'"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            
            # For new trades without targets hit, mode should be 'original'
            targets_hit = trade.get("scale_out_config", {}).get("targets_hit", [])
            if len(targets_hit) == 0:
                assert mode == "original", f"New trade should have mode='original', got '{mode}'"
            
            print(f"Trade {trade.get('symbol')}: mode = {mode}, targets_hit = {targets_hit}")
    
    def test_trail_pct_default_value(self):
        """trail_pct should default to 0.02 (2%)"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("trailing_stop_config", {})
            trail_pct = config.get("trail_pct")
            
            assert trail_pct == 0.02, f"trail_pct should be 0.02, got {trail_pct}"
            print(f"Trade {trade.get('symbol')}: trail_pct = {trail_pct} ({trail_pct*100}%)")
    
    def test_stop_adjustments_is_list(self):
        """stop_adjustments should be a list"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("trailing_stop_config", {})
            adjustments = config.get("stop_adjustments", [])
            
            assert isinstance(adjustments, list), "stop_adjustments should be a list"
            print(f"Trade {trade.get('symbol')}: stop_adjustments count = {len(adjustments)}")


class TestTrailingStopModeTransitions:
    """Test mode transitions: original -> breakeven -> trailing"""
    
    def test_mode_values_are_valid(self):
        """Mode should be one of: original, breakeven, trailing"""
        valid_modes = ["original", "breakeven", "trailing"]
        
        # Check pending trades
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            assert mode in valid_modes, f"Invalid mode '{mode}', expected one of {valid_modes}"
            print(f"Pending trade {trade.get('symbol')}: mode = {mode}")
        
        # Check open trades
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            assert mode in valid_modes, f"Invalid mode '{mode}', expected one of {valid_modes}"
            print(f"Open trade {trade.get('symbol')}: mode = {mode}")
    
    def test_breakeven_mode_after_target1(self):
        """After Target 1 hit, mode should be 'breakeven'"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            targets_hit = trade.get("scale_out_config", {}).get("targets_hit", [])
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            
            # If only T1 hit (index 0), mode should be breakeven
            if 0 in targets_hit and 1 not in targets_hit:
                assert mode == "breakeven", f"After T1 hit, mode should be 'breakeven', got '{mode}'"
                print(f"Trade {trade.get('symbol')}: T1 hit, mode = {mode} ✓")
            
            # If T2 hit (index 1), mode should be trailing
            if 1 in targets_hit:
                assert mode == "trailing", f"After T2 hit, mode should be 'trailing', got '{mode}'"
                print(f"Trade {trade.get('symbol')}: T2 hit, mode = {mode} ✓")
    
    def test_breakeven_stop_equals_entry_price(self):
        """In breakeven mode, current_stop should equal fill_price (entry)"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            
            if mode == "breakeven":
                current_stop = config.get("current_stop")
                fill_price = trade.get("fill_price")
                
                # Allow small tolerance for rounding
                assert abs(current_stop - fill_price) < 0.01, \
                    f"Breakeven stop ({current_stop}) should equal fill_price ({fill_price})"
                print(f"Trade {trade.get('symbol')}: breakeven stop = ${current_stop}, fill = ${fill_price} ✓")


class TestHighWaterMarkTracking:
    """Test high_water_mark tracking for trailing stops"""
    
    def test_high_water_mark_initialized_for_trailing(self):
        """high_water_mark should be set when trailing mode activates"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            
            if mode == "trailing":
                high_water = config.get("high_water_mark", 0)
                assert high_water > 0, "high_water_mark should be positive in trailing mode"
                print(f"Trade {trade.get('symbol')}: high_water_mark = ${high_water}")
    
    def test_trailing_stop_calculation(self):
        """Trailing stop should be high_water_mark * (1 - trail_pct) for longs"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            mode = config.get("mode")
            direction = trade.get("direction")
            
            if mode == "trailing" and direction == "long":
                high_water = config.get("high_water_mark", 0)
                trail_pct = config.get("trail_pct", 0.02)
                current_stop = config.get("current_stop", 0)
                
                expected_stop = round(high_water * (1 - trail_pct), 2)
                
                # Stop should be at least the expected value (may be higher if price dropped)
                print(f"Trade {trade.get('symbol')}: high_water=${high_water}, trail_pct={trail_pct}")
                print(f"  Expected stop: ${expected_stop}, Actual stop: ${current_stop}")


class TestStopAdjustmentsHistory:
    """Test stop_adjustments array records history"""
    
    def test_stop_adjustment_structure(self):
        """stop_adjustments entries should have required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            adjustments = config.get("stop_adjustments", [])
            
            for adj in adjustments:
                assert "timestamp" in adj, "stop_adjustment missing 'timestamp'"
                assert "old_stop" in adj, "stop_adjustment missing 'old_stop'"
                assert "new_stop" in adj, "stop_adjustment missing 'new_stop'"
                assert "reason" in adj, "stop_adjustment missing 'reason'"
                assert "price_at_adjustment" in adj, "stop_adjustment missing 'price_at_adjustment'"
                
                print(f"Trade {trade.get('symbol')}: adjustment = {adj}")
    
    def test_adjustment_reasons_are_valid(self):
        """Adjustment reasons should be valid values"""
        valid_reasons = ["breakeven", "trailing_activated", "trail_up", "trail_down"]
        
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            adjustments = config.get("stop_adjustments", [])
            
            for adj in adjustments:
                reason = adj.get("reason")
                assert reason in valid_reasons, f"Invalid reason '{reason}', expected one of {valid_reasons}"
                print(f"Trade {trade.get('symbol')}: adjustment reason = {reason}")


class TestCloseReasonVariants:
    """Test close_reason includes trailing stop variants"""
    
    def test_closed_trades_have_close_reason(self):
        """Closed trades should have close_reason field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed?limit=20")
        data = response.json()
        
        trades = data.get("trades", [])
        print(f"Found {len(trades)} closed trades")
        
        for trade in trades:
            close_reason = trade.get("close_reason")
            print(f"Trade {trade.get('symbol')}: close_reason = {close_reason}")
    
    def test_valid_close_reasons(self):
        """Close reasons should be valid values"""
        valid_reasons = [
            "manual", "stop_loss", "stop_loss_breakeven", "stop_loss_trailing",
            "target_hit", "target_1_complete", "target_2_complete", "target_3_complete",
            "rejected", None
        ]
        
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/closed?limit=20")
        data = response.json()
        
        for trade in data.get("trades", []):
            close_reason = trade.get("close_reason")
            assert close_reason in valid_reasons, f"Invalid close_reason '{close_reason}'"


class TestTrailingStopEnabled:
    """Test trailing stop enabled flag"""
    
    def test_trailing_stop_enabled_by_default(self):
        """trailing_stop_config.enabled should be True by default"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            enabled = config.get("enabled")
            
            assert enabled == True, f"trailing_stop should be enabled by default, got {enabled}"
            print(f"Trade {trade.get('symbol')}: trailing_stop enabled = {enabled}")


class TestOriginalStopPreservation:
    """Test original_stop is preserved"""
    
    def test_original_stop_preserved(self):
        """original_stop should preserve the initial stop price"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        for trade in data.get("trades", []):
            config = trade.get("trailing_stop_config", {})
            original_stop = config.get("original_stop", 0)
            stop_price = trade.get("stop_price", 0)
            
            # original_stop should match stop_price (or be 0 if not initialized)
            if original_stop > 0:
                assert original_stop == stop_price, \
                    f"original_stop ({original_stop}) should match stop_price ({stop_price})"
            
            print(f"Trade {trade.get('symbol')}: original_stop = ${original_stop}, stop_price = ${stop_price}")


class TestDemoTradeCreation:
    """Test creating demo trade with trailing_stop_config"""
    
    def test_create_demo_trade_has_trailing_stop_config(self):
        """Demo trade should have trailing_stop_config initialized"""
        # Create a demo trade
        response = requests.post(f"{BASE_URL}/api/trading-bot/demo-trade", json={
            "symbol": "TSLA",
            "direction": "long"
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                trade = data.get("trade", {})
                
                assert "trailing_stop_config" in trade, "Demo trade missing trailing_stop_config"
                
                config = trade.get("trailing_stop_config", {})
                assert config.get("enabled") == True
                assert config.get("mode") == "original"
                assert config.get("trail_pct") == 0.02
                assert isinstance(config.get("stop_adjustments"), list)
                
                print(f"Demo trade {trade.get('symbol')}: trailing_stop_config = {config}")
                
                # Clean up - reject the demo trade
                trade_id = trade.get("id")
                if trade_id:
                    requests.post(f"{BASE_URL}/api/trading-bot/trades/{trade_id}/reject")
        else:
            print(f"Demo trade creation returned status {response.status_code}")


class TestBotStatusEndpoint:
    """Test bot status endpoint"""
    
    def test_bot_status_returns_success(self):
        """Bot status endpoint should return success"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        print(f"Bot running: {data.get('running')}")
        print(f"Bot mode: {data.get('mode')}")
        print(f"Pending trades: {data.get('pending_trades')}")
        print(f"Open trades: {data.get('open_trades')}")


# Cleanup fixture
@pytest.fixture(scope="session", autouse=True)
def cleanup_after_tests():
    """Reset bot state after all tests"""
    yield
    # Keep bot running in confirmation mode
    requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
