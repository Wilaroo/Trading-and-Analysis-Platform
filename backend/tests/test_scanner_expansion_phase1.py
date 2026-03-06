"""
Scanner Expansion Phase 1 - Backend Tests
Testing new scanner setups: Squeeze Detection, Gap & Go/Gap Fade, 
Opening Range Breakout, Relative Strength vs SPY, Mean Reversion
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ==============================================================================
# Module: Health & Basic API Tests
# ==============================================================================

class TestHealthAndBasicAPIs:
    """Basic health check and API availability tests"""
    
    def test_health_endpoint(self):
        """Test /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health check passed: {data}")

    def test_backend_accessible(self):
        """Verify backend API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print(f"✓ Backend accessible at {BASE_URL}")


# ==============================================================================
# Module: Technical Snapshot API - New Indicator Fields
# ==============================================================================

class TestTechnicalSnapshotNewFields:
    """Test /api/technicals/{symbol} returns new indicator fields"""
    
    @pytest.fixture(scope="class")
    def aapl_technicals(self):
        """Fetch AAPL technicals once for all tests in class"""
        response = requests.get(f"{BASE_URL}/api/technicals/AAPL")
        assert response.status_code == 200
        return response.json()
    
    @pytest.fixture(scope="class")
    def nvda_technicals(self):
        """Fetch NVDA technicals once for all tests in class"""
        response = requests.get(f"{BASE_URL}/api/technicals/NVDA")
        assert response.status_code == 200
        return response.json()
    
    @pytest.fixture(scope="class")
    def tsla_technicals(self):
        """Fetch TSLA technicals once for all tests in class"""
        response = requests.get(f"{BASE_URL}/api/technicals/TSLA")
        assert response.status_code == 200
        return response.json()
    
    def test_aapl_technicals_success(self, aapl_technicals):
        """Test AAPL technicals returns success"""
        assert aapl_technicals.get("success") is True
        assert aapl_technicals.get("symbol") == "AAPL"
        print(f"✓ AAPL technicals returned successfully")
    
    def test_aapl_has_bollinger_bands(self, aapl_technicals):
        """Test AAPL has bollinger_bands field with upper, middle, lower, width"""
        bb = aapl_technicals.get("bollinger_bands")
        assert bb is not None, "bollinger_bands field missing"
        assert "upper" in bb, "bollinger_bands.upper missing"
        assert "middle" in bb, "bollinger_bands.middle missing"
        assert "lower" in bb, "bollinger_bands.lower missing"
        assert "width" in bb, "bollinger_bands.width missing"
        # Verify values are numeric
        assert isinstance(bb["upper"], (int, float)), "bollinger_bands.upper not numeric"
        assert isinstance(bb["middle"], (int, float)), "bollinger_bands.middle not numeric"
        assert isinstance(bb["lower"], (int, float)), "bollinger_bands.lower not numeric"
        assert isinstance(bb["width"], (int, float)), "bollinger_bands.width not numeric"
        # Verify logical relationship: lower < middle < upper
        assert bb["lower"] < bb["middle"] < bb["upper"], "BB bands out of order"
        print(f"✓ AAPL Bollinger Bands: upper={bb['upper']}, middle={bb['middle']}, lower={bb['lower']}, width={bb['width']:.2f}%")
    
    def test_aapl_has_keltner_channels(self, aapl_technicals):
        """Test AAPL has keltner_channels field with upper, middle, lower"""
        kc = aapl_technicals.get("keltner_channels")
        assert kc is not None, "keltner_channels field missing"
        assert "upper" in kc, "keltner_channels.upper missing"
        assert "middle" in kc, "keltner_channels.middle missing"
        assert "lower" in kc, "keltner_channels.lower missing"
        # Verify values are numeric
        assert isinstance(kc["upper"], (int, float)), "keltner_channels.upper not numeric"
        assert isinstance(kc["middle"], (int, float)), "keltner_channels.middle not numeric"
        assert isinstance(kc["lower"], (int, float)), "keltner_channels.lower not numeric"
        # Verify logical relationship: lower < middle < upper
        assert kc["lower"] < kc["middle"] < kc["upper"], "KC channels out of order"
        print(f"✓ AAPL Keltner Channels: upper={kc['upper']}, middle={kc['middle']}, lower={kc['lower']}")
    
    def test_aapl_has_squeeze_fields(self, aapl_technicals):
        """Test AAPL has squeeze field with on (boolean) and fire (momentum)"""
        squeeze = aapl_technicals.get("squeeze")
        assert squeeze is not None, "squeeze field missing"
        assert "on" in squeeze, "squeeze.on missing"
        assert "fire" in squeeze, "squeeze.fire missing"
        # Verify types
        assert isinstance(squeeze["on"], bool), "squeeze.on should be boolean"
        assert isinstance(squeeze["fire"], (int, float)), "squeeze.fire should be numeric"
        print(f"✓ AAPL Squeeze: on={squeeze['on']}, fire={squeeze['fire']:.3f}")
    
    def test_aapl_has_opening_range(self, aapl_technicals):
        """Test AAPL has opening_range field with high, low, breakout"""
        or_data = aapl_technicals.get("opening_range")
        assert or_data is not None, "opening_range field missing"
        assert "high" in or_data, "opening_range.high missing"
        assert "low" in or_data, "opening_range.low missing"
        assert "breakout" in or_data, "opening_range.breakout missing"
        # Verify values
        assert isinstance(or_data["high"], (int, float)), "opening_range.high not numeric"
        assert isinstance(or_data["low"], (int, float)), "opening_range.low not numeric"
        assert or_data["breakout"] in ["above", "below", "inside"], f"Invalid breakout value: {or_data['breakout']}"
        # Verify logical relationship: low < high
        assert or_data["low"] <= or_data["high"], "OR low > high"
        print(f"✓ AAPL Opening Range: high={or_data['high']}, low={or_data['low']}, breakout={or_data['breakout']}")
    
    def test_aapl_has_relative_strength(self, aapl_technicals):
        """Test AAPL has relative_strength field with vs_spy value"""
        rs = aapl_technicals.get("relative_strength")
        assert rs is not None, "relative_strength field missing"
        assert "vs_spy" in rs, "relative_strength.vs_spy missing"
        # Verify numeric
        assert isinstance(rs["vs_spy"], (int, float)), "relative_strength.vs_spy not numeric"
        print(f"✓ AAPL Relative Strength vs SPY: {rs['vs_spy']:+.2f}%")
    
    def test_nvda_technicals_success(self, nvda_technicals):
        """Test NVDA technicals returns success with all new fields"""
        assert nvda_technicals.get("success") is True
        assert nvda_technicals.get("symbol") == "NVDA"
        # Verify all new fields exist
        assert "bollinger_bands" in nvda_technicals
        assert "keltner_channels" in nvda_technicals
        assert "squeeze" in nvda_technicals
        assert "opening_range" in nvda_technicals
        assert "relative_strength" in nvda_technicals
        print(f"✓ NVDA has all new technical fields")
    
    def test_nvda_bollinger_bands_valid(self, nvda_technicals):
        """Test NVDA Bollinger Bands have valid numeric data"""
        bb = nvda_technicals.get("bollinger_bands", {})
        assert bb["upper"] > 0, "NVDA BB upper should be positive"
        assert bb["middle"] > 0, "NVDA BB middle should be positive"
        assert bb["lower"] > 0, "NVDA BB lower should be positive"
        assert bb["width"] >= 0, "NVDA BB width should be non-negative"
        print(f"✓ NVDA BB width: {bb['width']:.2f}%")
    
    def test_tsla_technicals_success(self, tsla_technicals):
        """Test TSLA technicals returns success with new fields"""
        assert tsla_technicals.get("success") is True
        assert tsla_technicals.get("symbol") == "TSLA"
        bb = tsla_technicals.get("bollinger_bands")
        assert bb is not None
        squeeze = tsla_technicals.get("squeeze")
        assert squeeze is not None
        print(f"✓ TSLA: BB width={bb.get('width', 0):.2f}%, Squeeze on={squeeze.get('on')}")


# ==============================================================================
# Module: Live Scanner Status - 34 Enabled Setups
# ==============================================================================

class TestLiveScannerStatus:
    """Test /api/live-scanner/status shows 34 setups including new ones"""
    
    @pytest.fixture(scope="class")
    def scanner_status(self):
        """Fetch scanner status once for all tests"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/status")
        assert response.status_code == 200
        return response.json()
    
    def test_scanner_status_success(self, scanner_status):
        """Test scanner status returns success"""
        assert scanner_status.get("success") is True
        print(f"✓ Scanner status returned successfully")
    
    def test_scanner_running(self, scanner_status):
        """Test scanner running status"""
        running = scanner_status.get("running")
        # Scanner may or may not be running outside market hours
        assert isinstance(running, bool), "running should be boolean"
        print(f"✓ Scanner running: {running}")
    
    def test_scanner_has_enabled_setups(self, scanner_status):
        """Test scanner has enabled_setups field"""
        enabled_setups = scanner_status.get("enabled_setups")
        assert enabled_setups is not None, "enabled_setups field missing"
        assert isinstance(enabled_setups, list), "enabled_setups should be a list"
        print(f"✓ Scanner has {len(enabled_setups)} enabled setups")
    
    def test_scanner_has_34_setups(self, scanner_status):
        """Test scanner has approximately 34 enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        # Allow some flexibility (30-40 setups)
        assert len(enabled_setups) >= 30, f"Expected 30+ setups, got {len(enabled_setups)}"
        assert len(enabled_setups) <= 40, f"Expected <= 40 setups, got {len(enabled_setups)}"
        print(f"✓ Scanner has {len(enabled_setups)} setups (expected ~34)")
    
    def test_scanner_has_squeeze_setup(self, scanner_status):
        """Test scanner has 'squeeze' in enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        assert "squeeze" in enabled_setups, "squeeze setup missing from enabled_setups"
        print(f"✓ Scanner has 'squeeze' setup enabled")
    
    def test_scanner_has_mean_reversion_setup(self, scanner_status):
        """Test scanner has 'mean_reversion' in enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        assert "mean_reversion" in enabled_setups, "mean_reversion setup missing from enabled_setups"
        print(f"✓ Scanner has 'mean_reversion' setup enabled")
    
    def test_scanner_has_relative_strength_setup(self, scanner_status):
        """Test scanner has 'relative_strength' in enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        assert "relative_strength" in enabled_setups, "relative_strength setup missing from enabled_setups"
        print(f"✓ Scanner has 'relative_strength' setup enabled")
    
    def test_scanner_has_gap_fade_setup(self, scanner_status):
        """Test scanner has 'gap_fade' in enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        assert "gap_fade" in enabled_setups, "gap_fade setup missing from enabled_setups"
        print(f"✓ Scanner has 'gap_fade' setup enabled")
    
    def test_scanner_has_orb_setup(self, scanner_status):
        """Test scanner has 'orb' (Opening Range Breakout) in enabled setups"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        assert "orb" in enabled_setups, "orb setup missing from enabled_setups"
        print(f"✓ Scanner has 'orb' (Opening Range Breakout) setup enabled")
    
    def test_list_all_enabled_setups(self, scanner_status):
        """List all enabled setups for reference"""
        enabled_setups = scanner_status.get("enabled_setups", [])
        print(f"\n=== All {len(enabled_setups)} Enabled Setups ===")
        for setup in sorted(enabled_setups):
            print(f"  - {setup}")


# ==============================================================================
# Module: Live Scanner Config - Volume Filters
# ==============================================================================

class TestLiveScannerConfig:
    """Test scanner configuration endpoints"""
    
    def test_get_config(self):
        """Test getting scanner configuration"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/config")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "enabled_setups" in data
        assert "scan_interval" in data
        print(f"✓ Scanner config: interval={data.get('scan_interval')}s, setups={len(data.get('enabled_setups', []))}")
    
    def test_get_volume_filter_config(self):
        """Test getting volume filter configuration"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/config/volume-filter")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "min_adv_general" in data
        assert "min_adv_intraday" in data
        print(f"✓ Volume filters: General>={data.get('min_adv_general', 0):,}, Intraday>={data.get('min_adv_intraday', 0):,}")


# ==============================================================================
# Module: Live Scanner Alerts
# ==============================================================================

class TestLiveScannerAlerts:
    """Test scanner alerts endpoint"""
    
    def test_get_alerts(self):
        """Test getting live alerts from scanner"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "alerts" in data
        assert "count" in data
        alerts = data.get("alerts", [])
        # May have 0 alerts outside market hours
        print(f"✓ Scanner alerts: {data.get('count')} alerts")
        if alerts:
            # Check first alert structure
            first = alerts[0]
            assert "symbol" in first
            assert "setup_type" in first
            print(f"  First alert: {first.get('symbol')} - {first.get('setup_type')}")


# ==============================================================================
# Module: Batch Technical Snapshot
# ==============================================================================

class TestBatchTechnicals:
    """Test batch technical snapshot endpoint"""
    
    def test_batch_technicals(self):
        """Test batch technicals for multiple symbols"""
        response = requests.post(
            f"{BASE_URL}/api/technicals/batch",
            json=["AAPL", "NVDA", "TSLA"]
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("count") >= 1
        technicals = data.get("technicals", {})
        
        # Check at least one symbol has all new fields
        for symbol, tech in technicals.items():
            assert "bollinger_bands" in tech, f"{symbol} missing bollinger_bands"
            assert "keltner_channels" in tech, f"{symbol} missing keltner_channels"
            assert "squeeze" in tech, f"{symbol} missing squeeze"
            assert "opening_range" in tech, f"{symbol} missing opening_range"
            assert "relative_strength" in tech, f"{symbol} missing relative_strength"
            print(f"✓ {symbol}: BB width={tech['bollinger_bands'].get('width', 0):.2f}%, squeeze={tech['squeeze'].get('on')}")


# ==============================================================================
# Module: Strategy Stats
# ==============================================================================

class TestStrategyStats:
    """Test strategy win-rate statistics endpoint"""
    
    def test_get_all_strategy_stats(self):
        """Test getting all strategy statistics"""
        response = requests.get(f"{BASE_URL}/api/live-scanner/stats/strategies")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "stats" in data
        stats = data.get("stats", {})
        print(f"✓ Strategy stats for {len(stats)} setups")
        
        # Check new setups exist in stats
        new_setups = ["squeeze", "mean_reversion", "relative_strength", "gap_fade"]
        for setup in new_setups:
            if setup in stats:
                print(f"  {setup}: win_rate={stats[setup].get('win_rate', 0):.1%}")


# ==============================================================================
# Run tests
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
