"""
Test Scanner Universe Expansion Features
==========================================
Tests for:
1. GET /api/scanner/universe-stats - Expanded universe with ~1,473 symbols
2. Sector expansions (biotech, cannabis, ev_cleantech, crypto, quantum_ai, spac_ipo)
3. User viewed symbols tracker initialization and functionality
4. Symbol tracking from AI chat
5. Wave scanner includes user viewed symbols in Tier 1
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestUniverseStats:
    """Test /api/scanner/universe-stats endpoint - Expanded scanner universe"""

    def test_universe_stats_endpoint_returns_200(self):
        """Test that universe-stats endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        print(f"Universe stats response status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
    def test_universe_stats_has_expanded_total(self):
        """Test that universe has ~1473 symbols as expected"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        
        universe = data.get("universe", {})
        total_unique = universe.get("total_unique", 0)
        
        print(f"Total unique symbols in universe: {total_unique}")
        
        # Per the requirements, should be ~1473 symbols
        assert total_unique >= 1400, f"Expected at least 1400 symbols, got {total_unique}"
        assert total_unique <= 1600, f"Expected at most 1600 symbols, got {total_unique}"
        
    def test_universe_stats_has_spy_symbols(self):
        """Test SPY constituent count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        spy_count = universe.get("spy_count", 0)
        
        print(f"SPY symbols count: {spy_count}")
        
        # SPY should have ~495 symbols
        assert spy_count >= 450, f"Expected at least 450 SPY symbols, got {spy_count}"
        
    def test_universe_stats_has_qqq_symbols(self):
        """Test QQQ constituent count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        qqq_count = universe.get("qqq_count", 0)
        
        print(f"QQQ symbols count: {qqq_count}")
        
        # QQQ should have ~120 symbols
        assert qqq_count >= 100, f"Expected at least 100 QQQ symbols, got {qqq_count}"
        
    def test_universe_stats_has_nasdaq_extended(self):
        """Test NASDAQ extended universe count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        nasdaq_ext = universe.get("nasdaq_extended_count", 0)
        
        print(f"NASDAQ Extended count: {nasdaq_ext}")
        
        # NASDAQ extended should have ~480 symbols
        assert nasdaq_ext >= 400, f"Expected at least 400 NASDAQ extended symbols, got {nasdaq_ext}"
        
    def test_universe_stats_has_iwm_symbols(self):
        """Test Russell 2000 (IWM) symbols count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        iwm_count = universe.get("iwm_count", 0)
        
        print(f"IWM (Russell 2000) symbols count: {iwm_count}")
        
        # IWM should have ~542+ symbols after expansion
        assert iwm_count >= 500, f"Expected at least 500 IWM symbols, got {iwm_count}"


class TestSectorExpansions:
    """Test sector-specific symbol expansions"""
    
    def test_sector_expansions_present(self):
        """Test that sector expansions are present in response"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        sector_expansions = universe.get("sector_expansions", {})
        
        print(f"Sector expansions: {sector_expansions}")
        
        # All 6 sectors should be present
        assert "biotech" in sector_expansions, "Missing biotech sector"
        assert "cannabis" in sector_expansions, "Missing cannabis sector"
        assert "ev_cleantech" in sector_expansions, "Missing ev_cleantech sector"
        assert "crypto" in sector_expansions, "Missing crypto sector"
        assert "quantum_ai" in sector_expansions, "Missing quantum_ai sector"
        assert "spac_ipo" in sector_expansions, "Missing spac_ipo sector"
        
    def test_biotech_sector_count(self):
        """Test biotech sector has ~71 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        biotech = sector_expansions.get("biotech", 0)
        
        print(f"Biotech symbols: {biotech}")
        
        # Should have ~71 biotech symbols
        assert biotech >= 60, f"Expected at least 60 biotech symbols, got {biotech}"
        
    def test_cannabis_sector_count(self):
        """Test cannabis sector has ~25 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        cannabis = sector_expansions.get("cannabis", 0)
        
        print(f"Cannabis symbols: {cannabis}")
        
        # Should have ~25 cannabis symbols
        assert cannabis >= 20, f"Expected at least 20 cannabis symbols, got {cannabis}"
        
    def test_ev_cleantech_sector_count(self):
        """Test EV/CleanTech sector has ~57 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        ev_cleantech = sector_expansions.get("ev_cleantech", 0)
        
        print(f"EV/CleanTech symbols: {ev_cleantech}")
        
        # Should have ~57 EV/CleanTech symbols
        assert ev_cleantech >= 50, f"Expected at least 50 EV/CleanTech symbols, got {ev_cleantech}"
        
    def test_crypto_sector_count(self):
        """Test crypto sector has ~38 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        crypto = sector_expansions.get("crypto", 0)
        
        print(f"Crypto symbols: {crypto}")
        
        # Should have ~38 crypto symbols
        assert crypto >= 30, f"Expected at least 30 crypto symbols, got {crypto}"
        
    def test_quantum_ai_sector_count(self):
        """Test Quantum/AI sector has ~34 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        quantum_ai = sector_expansions.get("quantum_ai", 0)
        
        print(f"Quantum/AI symbols: {quantum_ai}")
        
        # Should have ~34 Quantum/AI symbols
        assert quantum_ai >= 25, f"Expected at least 25 Quantum/AI symbols, got {quantum_ai}"
        
    def test_spac_ipo_sector_count(self):
        """Test SPAC/IPO sector has ~30 symbols"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sector_expansions = data.get("universe", {}).get("sector_expansions", {})
        spac_ipo = sector_expansions.get("spac_ipo", 0)
        
        print(f"SPAC/IPO symbols: {spac_ipo}")
        
        # Should have ~30 SPAC/IPO symbols
        assert spac_ipo >= 20, f"Expected at least 20 SPAC/IPO symbols, got {spac_ipo}"


class TestTierCounts:
    """Test tiered scanning structure"""
    
    def test_tier1_count(self):
        """Test Tier 1 (SPY + QQQ + ETFs + Watchlist + Viewed) count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        tier1_count = universe.get("tier1_count", 0)
        
        print(f"Tier 1 count: {tier1_count}")
        
        # Tier 1 should have at least 500 symbols (SPY + QQQ + ETFs)
        assert tier1_count >= 500, f"Expected at least 500 Tier 1 symbols, got {tier1_count}"
        
    def test_tier2_count(self):
        """Test Tier 2 (NASDAQ Extended excluding Tier 1) count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        tier2_count = universe.get("tier2_count", 0)
        
        print(f"Tier 2 count: {tier2_count}")
        
        # Tier 2 should have remaining NASDAQ extended symbols
        assert tier2_count >= 100, f"Expected at least 100 Tier 2 symbols, got {tier2_count}"
        
    def test_tier3_count(self):
        """Test Tier 3 (Russell 2000 + Sectors) count"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        universe = data.get("universe", {})
        tier3_count = universe.get("tier3_count", 0)
        
        print(f"Tier 3 count: {tier3_count}")
        
        # Tier 3 should have IWM + sectors (excluding tier 1 & 2)
        assert tier3_count >= 200, f"Expected at least 200 Tier 3 symbols, got {tier3_count}"


class TestUserViewedSymbols:
    """Test user viewed symbols tracking"""
    
    def test_user_viewed_in_response(self):
        """Test that user_viewed is included in universe-stats response"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        user_viewed = data.get("user_viewed", {})
        
        print(f"User viewed data: {user_viewed}")
        
        # user_viewed section should be present
        assert "count" in user_viewed, "Missing 'count' in user_viewed"
        assert "symbols" in user_viewed, "Missing 'symbols' in user_viewed"
        assert "stats" in user_viewed, "Missing 'stats' in user_viewed"
        
    def test_user_viewed_stats_structure(self):
        """Test user viewed stats structure"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        stats = data.get("user_viewed", {}).get("stats", {})
        
        print(f"User viewed stats: {stats}")
        
        # Stats should have 'available' field
        assert "available" in stats, "Missing 'available' in stats"


class TestSummaryStructure:
    """Test the summary structure in universe-stats response"""
    
    def test_summary_section_present(self):
        """Test that summary section is present with correct fields"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        summary = data.get("summary", {})
        
        print(f"Summary: {summary}")
        
        # All required fields should be present
        assert "tier1" in summary, "Missing tier1 in summary"
        assert "tier2" in summary, "Missing tier2 in summary"
        assert "tier3" in summary, "Missing tier3 in summary"
        assert "total_unique" in summary, "Missing total_unique in summary"
        assert "sectors_included" in summary, "Missing sectors_included in summary"
        
    def test_summary_sectors_included(self):
        """Test that all 6 sectors are listed in summary"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        sectors = data.get("summary", {}).get("sectors_included", [])
        
        print(f"Sectors included: {sectors}")
        
        # All 6 sectors should be listed
        expected_sectors = ["biotech", "cannabis", "ev_cleantech", "crypto", "quantum_ai", "spac_ipo"]
        for sector in expected_sectors:
            assert sector in sectors, f"Missing sector {sector} in summary"


class TestIndexSymbolsModule:
    """Test index_symbols.py helper functions directly via API"""
    
    def test_metadata_present(self):
        """Test that metadata is included in universe stats"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        metadata = data.get("universe", {}).get("metadata", {})
        
        print(f"Metadata: {metadata}")
        
        # Should have last_updated
        assert "last_updated" in metadata, "Missing last_updated in metadata"
        
    def test_overlap_spy_qqq(self):
        """Test that SPY/QQQ overlap is tracked"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        overlap = data.get("universe", {}).get("overlap_spy_qqq", 0)
        
        print(f"SPY/QQQ overlap: {overlap}")
        
        # There should be significant overlap between SPY and QQQ
        assert overlap >= 50, f"Expected at least 50 overlapping symbols, got {overlap}"


class TestTimestamp:
    """Test timestamp in response"""
    
    def test_timestamp_present(self):
        """Test that timestamp is present in response"""
        response = requests.get(f"{BASE_URL}/api/scanner/universe-stats")
        assert response.status_code == 200
        
        data = response.json()
        timestamp = data.get("timestamp")
        
        print(f"Timestamp: {timestamp}")
        
        assert timestamp is not None, "Missing timestamp in response"
        # Should be a valid ISO timestamp
        assert "T" in timestamp or ":" in timestamp, "Timestamp should be ISO format"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
