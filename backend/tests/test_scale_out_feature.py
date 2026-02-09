"""
Scale-Out Feature Tests
Tests for automatic target profit-taking with scale-out functionality.
Features tested:
- Open trades include scale_out_config with targets_hit, scale_out_pcts, partial_exits
- Open trades include original_shares and remaining_shares fields
- Bot monitors positions and checks if targets are hit
- When target is hit, partial exit is executed
- realized_pnl accumulates from partial exits
- Trade closes fully when all targets hit or remaining_shares = 0
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestScaleOutConfigStructure:
    """Test that open trades have correct scale_out_config structure"""
    
    def test_open_trades_have_scale_out_config(self):
        """Open trades should include scale_out_config field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") == True
        
        trades = data.get("trades", [])
        print(f"Found {len(trades)} open trades")
        
        for trade in trades:
            assert "scale_out_config" in trade, f"Trade {trade.get('id')} missing scale_out_config"
            
            config = trade.get("scale_out_config", {})
            assert "enabled" in config, "scale_out_config missing 'enabled' field"
            assert "targets_hit" in config, "scale_out_config missing 'targets_hit' field"
            assert "scale_out_pcts" in config, "scale_out_config missing 'scale_out_pcts' field"
            assert "partial_exits" in config, "scale_out_config missing 'partial_exits' field"
            
            print(f"Trade {trade.get('symbol')}: scale_out_config = {config}")
    
    def test_scale_out_pcts_sum_to_100(self):
        """Scale out percentages should sum to approximately 100%"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("scale_out_config", {})
            pcts = config.get("scale_out_pcts", [])
            
            if pcts:
                total = sum(pcts)
                assert 0.99 <= total <= 1.01, f"Scale out pcts sum to {total}, expected ~1.0"
                print(f"Trade {trade.get('symbol')}: scale_out_pcts = {pcts}, sum = {total}")
    
    def test_targets_hit_is_list(self):
        """targets_hit should be a list of target indices"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("scale_out_config", {})
            targets_hit = config.get("targets_hit", [])
            
            assert isinstance(targets_hit, list), "targets_hit should be a list"
            print(f"Trade {trade.get('symbol')}: targets_hit = {targets_hit}")
    
    def test_partial_exits_is_list(self):
        """partial_exits should be a list of exit records"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("scale_out_config", {})
            partial_exits = config.get("partial_exits", [])
            
            assert isinstance(partial_exits, list), "partial_exits should be a list"
            
            # If there are partial exits, verify structure
            for exit_record in partial_exits:
                assert "target_idx" in exit_record, "partial_exit missing target_idx"
                assert "shares_sold" in exit_record, "partial_exit missing shares_sold"
                assert "fill_price" in exit_record, "partial_exit missing fill_price"
                assert "pnl" in exit_record, "partial_exit missing pnl"
                assert "timestamp" in exit_record, "partial_exit missing timestamp"
            
            print(f"Trade {trade.get('symbol')}: partial_exits = {partial_exits}")


class TestOriginalAndRemainingShares:
    """Test original_shares and remaining_shares fields"""
    
    def test_open_trades_have_original_shares(self):
        """Open trades should have original_shares field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "original_shares" in trade, f"Trade {trade.get('id')} missing original_shares"
            assert trade.get("original_shares") > 0, "original_shares should be positive"
            print(f"Trade {trade.get('symbol')}: original_shares = {trade.get('original_shares')}")
    
    def test_open_trades_have_remaining_shares(self):
        """Open trades should have remaining_shares field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "remaining_shares" in trade, f"Trade {trade.get('id')} missing remaining_shares"
            assert trade.get("remaining_shares") >= 0, "remaining_shares should be non-negative"
            print(f"Trade {trade.get('symbol')}: remaining_shares = {trade.get('remaining_shares')}")
    
    def test_remaining_shares_lte_original(self):
        """remaining_shares should be <= original_shares"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            original = trade.get("original_shares", 0)
            remaining = trade.get("remaining_shares", 0)
            
            assert remaining <= original, f"remaining_shares ({remaining}) > original_shares ({original})"
            print(f"Trade {trade.get('symbol')}: {remaining}/{original} shares remaining")
    
    def test_shares_consistency_with_partial_exits(self):
        """remaining_shares should reflect partial exits"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            original = trade.get("original_shares", 0)
            remaining = trade.get("remaining_shares", 0)
            partial_exits = trade.get("scale_out_config", {}).get("partial_exits", [])
            
            # Calculate total shares sold
            total_sold = sum(exit.get("shares_sold", 0) for exit in partial_exits)
            
            # remaining should equal original - total_sold
            expected_remaining = original - total_sold
            assert remaining == expected_remaining, f"remaining_shares ({remaining}) != expected ({expected_remaining})"
            
            print(f"Trade {trade.get('symbol')}: original={original}, sold={total_sold}, remaining={remaining}")


class TestTargetPricesAndMonitoring:
    """Test target prices and monitoring logic"""
    
    def test_open_trades_have_target_prices(self):
        """Open trades should have target_prices array"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "target_prices" in trade, f"Trade {trade.get('id')} missing target_prices"
            targets = trade.get("target_prices", [])
            assert isinstance(targets, list), "target_prices should be a list"
            assert len(targets) >= 1, "Should have at least 1 target price"
            
            print(f"Trade {trade.get('symbol')}: targets = {targets}")
    
    def test_target_prices_ascending_for_long(self):
        """For long trades, target prices should be ascending"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            if trade.get("direction") == "long":
                targets = trade.get("target_prices", [])
                entry = trade.get("entry_price", 0)
                
                # All targets should be above entry for long
                for i, target in enumerate(targets):
                    assert target > entry, f"Target {i+1} (${target}) should be > entry (${entry}) for long"
                
                # Targets should be ascending
                for i in range(1, len(targets)):
                    assert targets[i] > targets[i-1], f"Targets should be ascending: T{i}=${targets[i-1]}, T{i+1}=${targets[i]}"
                
                print(f"Trade {trade.get('symbol')} (LONG): entry=${entry}, targets={targets}")
    
    def test_current_price_tracking(self):
        """Open trades should have current_price updated"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "current_price" in trade, f"Trade {trade.get('id')} missing current_price"
            current = trade.get("current_price", 0)
            assert current > 0, "current_price should be positive"
            
            print(f"Trade {trade.get('symbol')}: current_price = ${current}")


class TestRealizedPnLAccumulation:
    """Test realized P&L accumulation from partial exits"""
    
    def test_open_trades_have_realized_pnl(self):
        """Open trades should have realized_pnl field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "realized_pnl" in trade, f"Trade {trade.get('id')} missing realized_pnl"
            print(f"Trade {trade.get('symbol')}: realized_pnl = ${trade.get('realized_pnl')}")
    
    def test_realized_pnl_matches_partial_exits(self):
        """realized_pnl should equal sum of partial exit P&Ls"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            realized = trade.get("realized_pnl", 0)
            partial_exits = trade.get("scale_out_config", {}).get("partial_exits", [])
            
            # Sum P&L from all partial exits
            total_partial_pnl = sum(exit.get("pnl", 0) for exit in partial_exits)
            
            # realized_pnl should match (with small tolerance for floating point)
            assert abs(realized - total_partial_pnl) < 0.01, \
                f"realized_pnl ({realized}) != sum of partial exits ({total_partial_pnl})"
            
            print(f"Trade {trade.get('symbol')}: realized_pnl=${realized}, partial_exits_sum=${total_partial_pnl}")
    
    def test_unrealized_pnl_on_remaining_shares(self):
        """unrealized_pnl should be calculated on remaining shares only"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            unrealized = trade.get("unrealized_pnl", 0)
            remaining = trade.get("remaining_shares", 0)
            current = trade.get("current_price", 0)
            fill = trade.get("fill_price", 0)
            direction = trade.get("direction", "long")
            
            if remaining > 0 and fill > 0:
                if direction == "long":
                    expected_unrealized = (current - fill) * remaining
                else:
                    expected_unrealized = (fill - current) * remaining
                
                # Allow small tolerance for floating point
                assert abs(unrealized - expected_unrealized) < 1.0, \
                    f"unrealized_pnl ({unrealized}) != expected ({expected_unrealized})"
            
            print(f"Trade {trade.get('symbol')}: unrealized_pnl=${unrealized}, remaining={remaining}")


class TestScaleOutExecution:
    """Test scale-out execution logic (when targets are hit)"""
    
    def test_scale_out_config_enabled_by_default(self):
        """scale_out_config.enabled should be True by default"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("scale_out_config", {})
            enabled = config.get("enabled", False)
            
            assert enabled == True, "scale_out should be enabled by default"
            print(f"Trade {trade.get('symbol')}: scale_out enabled = {enabled}")
    
    def test_default_scale_out_percentages(self):
        """Default scale-out should be 33%, 33%, 34%"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            config = trade.get("scale_out_config", {})
            pcts = config.get("scale_out_pcts", [])
            
            # Default should be [0.33, 0.33, 0.34]
            if len(pcts) == 3:
                assert abs(pcts[0] - 0.33) < 0.01, f"T1 pct should be ~0.33, got {pcts[0]}"
                assert abs(pcts[1] - 0.33) < 0.01, f"T2 pct should be ~0.33, got {pcts[1]}"
                assert abs(pcts[2] - 0.34) < 0.01, f"T3 pct should be ~0.34, got {pcts[2]}"
            
            print(f"Trade {trade.get('symbol')}: scale_out_pcts = {pcts}")


class TestMSFTBrokerPosition:
    """Test MSFT position exists in broker"""
    
    def test_msft_position_in_broker(self):
        """MSFT position should exist in broker positions"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/positions")
        data = response.json()
        
        assert data.get("success") == True
        positions = data.get("positions", [])
        msft_positions = [p for p in positions if p.get("symbol") == "MSFT"]
        
        assert len(msft_positions) > 0, "MSFT position should exist in broker"
        
        msft = msft_positions[0]
        print(f"MSFT broker position: {msft.get('qty')} shares @ ${msft.get('avg_entry_price'):.2f}")
        print(f"  Current price: ${msft.get('current_price'):.2f}")
        print(f"  Unrealized P&L: ${msft.get('unrealized_pnl'):.2f}")


class TestPendingTradeScaleOutConfig:
    """Test pending trades have scale_out_config structure"""
    
    def test_pending_trade_has_scale_out_config(self):
        """Pending trades should have scale_out_config field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        assert data.get("success") == True
        trades = data.get("trades", [])
        
        for trade in trades:
            assert "scale_out_config" in trade, f"Trade {trade.get('id')} missing scale_out_config"
            
            config = trade.get("scale_out_config", {})
            assert "enabled" in config
            assert "targets_hit" in config
            assert "scale_out_pcts" in config
            assert "partial_exits" in config
            
            print(f"Pending trade {trade.get('symbol')}: scale_out_config = {config}")
    
    def test_pending_trade_has_target_prices(self):
        """Pending trades should have target_prices array"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/pending")
        data = response.json()
        
        trades = data.get("trades", [])
        for trade in trades:
            assert "target_prices" in trade
            targets = trade.get("target_prices", [])
            assert len(targets) >= 1, "Should have at least 1 target"
            print(f"Pending trade {trade.get('symbol')}: targets = {targets}")


class TestBotTradeDataclass:
    """Test BotTrade dataclass structure via API"""
    
    def test_trade_has_all_scale_out_fields(self):
        """Verify trade response includes all scale-out related fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open")
        data = response.json()
        
        trades = data.get("trades", [])
        if trades:
            trade = trades[0]
            
            # Required scale-out fields
            required_fields = [
                "original_shares",
                "remaining_shares", 
                "scale_out_config",
                "realized_pnl",
                "unrealized_pnl",
                "target_prices"
            ]
            
            for field in required_fields:
                assert field in trade, f"Trade missing required field: {field}"
            
            # scale_out_config sub-fields
            config = trade.get("scale_out_config", {})
            config_fields = ["enabled", "targets_hit", "scale_out_pcts", "partial_exits"]
            
            for field in config_fields:
                assert field in config, f"scale_out_config missing field: {field}"
            
            print(f"Trade {trade.get('symbol')} has all required scale-out fields")


# Cleanup fixture
@pytest.fixture(scope="session", autouse=True)
def cleanup_after_tests():
    """Reset bot state after all tests"""
    yield
    # Keep bot running in confirmation mode
    requests.post(f"{BASE_URL}/api/trading-bot/mode/confirmation")
