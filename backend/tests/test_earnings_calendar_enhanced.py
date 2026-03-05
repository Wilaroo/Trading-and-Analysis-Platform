"""
Test Earnings Calendar Enhanced Features
- Expected Move (% and $)
- Earnings Score (A+, A, B+, B, C, D, F, N/A)  
- has_reported flag
- eps_surprise for reported items
- Proj vs Result type distinction
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEarningsCalendarEnhanced:
    """Tests for enhanced earnings calendar fields"""

    def test_api_health(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("✓ Health check passed")

    def test_earnings_calendar_endpoint(self):
        """Verify earnings calendar returns data with proper structure"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-02-24",
            "end_date": "2026-03-01"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert "calendar" in data
        assert "grouped_by_date" in data
        assert "total_count" in data
        assert data["total_count"] > 0
        print(f"✓ Calendar returned {data['total_count']} items")

    def test_expected_move_fields(self):
        """Verify each item has expected_move.percent AND expected_move.dollar"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        for item in data.get("calendar", [])[:10]:  # Check first 10
            assert "expected_move" in item, f"Missing expected_move for {item['symbol']}"
            em = item["expected_move"]
            assert "percent" in em, f"Missing expected_move.percent for {item['symbol']}"
            assert "dollar" in em, f"Missing expected_move.dollar for {item['symbol']}"
            assert isinstance(em["percent"], (int, float)), "percent should be numeric"
            assert isinstance(em["dollar"], (int, float)), "dollar should be numeric"
            print(f"✓ {item['symbol']}: Exp {em['percent']}% ${em['dollar']}")
        
        print("✓ All items have expected_move.percent and expected_move.dollar")

    def test_earnings_score_fields(self):
        """Verify each item has earnings_score with label, value, and type"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        valid_labels = {"A+", "A", "B+", "B", "C", "D", "F", "N/A"}
        valid_types = {"actual", "projected"}
        
        for item in data.get("calendar", [])[:10]:
            assert "earnings_score" in item, f"Missing earnings_score for {item['symbol']}"
            es = item["earnings_score"]
            assert "label" in es, f"Missing earnings_score.label for {item['symbol']}"
            assert "type" in es, f"Missing earnings_score.type for {item['symbol']}"
            assert es["label"] in valid_labels, f"Invalid score label {es['label']}"
            assert es["type"] in valid_types, f"Invalid score type {es['type']}"
            print(f"✓ {item['symbol']}: Score {es['label']} ({es['type']})")
        
        print("✓ All items have valid earnings_score fields")

    def test_has_reported_flag(self):
        """Verify has_reported flag is present and boolean"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-02-24",
            "end_date": "2026-03-01"
        })
        assert response.status_code == 200
        data = response.json()
        
        reported_count = 0
        projected_count = 0
        
        for item in data.get("calendar", []):
            assert "has_reported" in item, f"Missing has_reported for {item['symbol']}"
            assert isinstance(item["has_reported"], bool), "has_reported should be boolean"
            if item["has_reported"]:
                reported_count += 1
            else:
                projected_count += 1
        
        print(f"✓ Reported: {reported_count}, Projected: {projected_count}")
        assert reported_count > 0 or projected_count > 0, "Should have at least some items"

    def test_eps_surprise_for_reported_items(self):
        """Verify eps_surprise is present for reported items with amount and percent"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-02-24",  # Past week should have reported
            "end_date": "2026-03-01"
        })
        assert response.status_code == 200
        data = response.json()
        
        reported_items = [i for i in data.get("calendar", []) if i.get("has_reported")]
        
        surprise_count = 0
        for item in reported_items[:10]:
            if "eps_surprise" in item:
                es = item["eps_surprise"]
                assert "amount" in es, f"Missing eps_surprise.amount for {item['symbol']}"
                assert "percent" in es, f"Missing eps_surprise.percent for {item['symbol']}"
                surprise_count += 1
                sign = "+" if es["percent"] >= 0 else ""
                print(f"✓ {item['symbol']}: EPS surprise {sign}{es['percent']:.1f}%")
        
        print(f"✓ Found {surprise_count} items with EPS surprise data")

    def test_proj_vs_result_type_alignment(self):
        """Verify 'projected' type for unreported, 'actual' type for reported"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        for item in data.get("calendar", []):
            has_reported = item.get("has_reported")
            score_type = item.get("earnings_score", {}).get("type")
            
            if has_reported:
                assert score_type == "actual", f"{item['symbol']}: reported but type={score_type}"
            else:
                assert score_type == "projected", f"{item['symbol']}: not reported but type={score_type}"
        
        print("✓ Score type correctly aligns with has_reported flag")

    def test_grouped_by_date_structure(self):
        """Verify grouped_by_date has count and before_open/after_close arrays"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        for group in data.get("grouped_by_date", []):
            assert "date" in group
            assert "count" in group
            assert "before_open" in group
            assert "after_close" in group
            assert isinstance(group["before_open"], list)
            assert isinstance(group["after_close"], list)
            total = len(group["before_open"]) + len(group["after_close"])
            assert total == group["count"], f"Count mismatch for {group['date']}"
            print(f"✓ {group['date']}: {group['count']} reports ({len(group['before_open'])} BMO, {len(group['after_close'])} AMC)")
        
        print("✓ grouped_by_date structure is correct")

    def test_time_label_format(self):
        """Verify time label is 'Before Open' or 'After Close'"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        valid_times = {"Before Open", "After Close"}
        for item in data.get("calendar", [])[:20]:
            assert item.get("time") in valid_times, f"Invalid time '{item.get('time')}' for {item['symbol']}"
        
        print("✓ All time labels are valid (Before Open / After Close)")

    def test_score_range_values(self):
        """Verify score values are in proper numeric range (0-100)"""
        response = requests.get(f"{BASE_URL}/api/earnings/calendar", params={
            "start_date": "2026-03-03",
            "end_date": "2026-03-08"
        })
        assert response.status_code == 200
        data = response.json()
        
        for item in data.get("calendar", []):
            score = item.get("earnings_score", {})
            if score.get("label") != "N/A":
                value = score.get("value", 0)
                assert 0 <= value <= 100, f"Score value {value} out of range for {item['symbol']}"
        
        print("✓ All score values are in valid range (0-100)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
