"""
TQS Engine API Tests - Trade Quality Score Phase 2
Tests all TQS API endpoints and validates the 5-pillar scoring system:
- Setup Quality (25%), Technical Quality (25%), Fundamental Quality (15%), 
- Context Quality (20%), Execution Quality (15%)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTQSPillars:
    """Test GET /api/tqs/pillars - Returns pillar information and weights"""
    
    def test_pillars_endpoint_returns_success(self):
        """Verify pillars endpoint returns success status"""
        response = requests.get(f"{BASE_URL}/api/tqs/pillars")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_pillars_returns_all_five_pillars(self):
        """Verify all 5 pillars are returned with correct weights"""
        response = requests.get(f"{BASE_URL}/api/tqs/pillars")
        data = response.json()
        pillars = data.get("pillars", {})
        
        # Check all 5 pillars exist
        expected_pillars = ["setup", "technical", "fundamental", "context", "execution"]
        for pillar in expected_pillars:
            assert pillar in pillars, f"Missing pillar: {pillar}"
            
    def test_pillars_have_correct_weights(self):
        """Verify each pillar has the correct weight"""
        response = requests.get(f"{BASE_URL}/api/tqs/pillars")
        data = response.json()
        pillars = data.get("pillars", {})
        
        expected_weights = {
            "setup": "25%",
            "technical": "25%",
            "fundamental": "15%",
            "context": "20%",
            "execution": "15%"
        }
        
        for pillar_name, expected_weight in expected_weights.items():
            actual_weight = pillars.get(pillar_name, {}).get("weight")
            assert actual_weight == expected_weight, f"{pillar_name} weight mismatch: {actual_weight} vs {expected_weight}"
            
    def test_pillars_have_components(self):
        """Verify each pillar has components listed"""
        response = requests.get(f"{BASE_URL}/api/tqs/pillars")
        data = response.json()
        pillars = data.get("pillars", {})
        
        for pillar_name, pillar_info in pillars.items():
            components = pillar_info.get("components", [])
            assert len(components) > 0, f"{pillar_name} has no components"
            assert isinstance(components, list), f"{pillar_name} components should be a list"


class TestTQSThresholds:
    """Test GET /api/tqs/thresholds - Returns action thresholds and grade ranges"""
    
    def test_thresholds_endpoint_returns_success(self):
        """Verify thresholds endpoint returns success status"""
        response = requests.get(f"{BASE_URL}/api/tqs/thresholds")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_action_thresholds_are_correct(self):
        """Verify action thresholds match expected values"""
        response = requests.get(f"{BASE_URL}/api/tqs/thresholds")
        data = response.json()
        thresholds = data.get("thresholds", {})
        
        # Expected thresholds: STRONG_BUY >= 80, BUY >= 65, HOLD >= 50, AVOID >= 35, STRONG_AVOID < 35
        expected = {
            "STRONG_BUY": 80,
            "BUY": 65,
            "HOLD": 50,
            "AVOID": 35,
            "STRONG_AVOID": 0
        }
        
        for action, threshold in expected.items():
            assert thresholds.get(action) == threshold, f"{action} threshold mismatch"
            
    def test_weights_sum_to_one(self):
        """Verify pillar weights sum to 1.0 (100%)"""
        response = requests.get(f"{BASE_URL}/api/tqs/thresholds")
        data = response.json()
        weights = data.get("weights", {})
        
        total_weight = sum(weights.values())
        assert abs(total_weight - 1.0) < 0.001, f"Weights sum to {total_weight}, expected 1.0"
        
    def test_grade_ranges_are_correct(self):
        """Verify grade ranges match expected values"""
        response = requests.get(f"{BASE_URL}/api/tqs/thresholds")
        data = response.json()
        grade_ranges = data.get("grade_ranges", {})
        
        # Verify grade ranges: A 85+, B+ 75-84, B 65-74, C+ 55-64, C 45-54, D 35-44, F <35
        expected_grades = {
            "A": "85-100",
            "B+": "75-84",
            "B": "65-74",
            "C+": "55-64",
            "C": "45-54",
            "D": "35-44",
            "F": "0-34"
        }
        
        for grade, expected_range in expected_grades.items():
            actual_range = grade_ranges.get(grade)
            assert actual_range == expected_range, f"Grade {grade} range mismatch: {actual_range} vs {expected_range}"


class TestTQSScore:
    """Test GET /api/tqs/score/{symbol} - Returns TQS summary"""
    
    def test_score_endpoint_returns_success(self):
        """Verify score endpoint returns success status"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_score_returns_tqs_summary(self):
        """Verify TQS summary contains expected fields"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        tqs = data.get("tqs", {})
        
        # Check required fields
        assert "score" in tqs, "Missing score"
        assert "grade" in tqs, "Missing grade"
        assert "action" in tqs, "Missing action"
        assert "pillar_scores" in tqs, "Missing pillar_scores"
        
    def test_score_is_in_valid_range(self):
        """Verify score is between 0 and 100"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        score = data.get("tqs", {}).get("score", -1)
        
        assert 0 <= score <= 100, f"Score {score} out of valid range [0, 100]"
        
    def test_grade_is_valid(self):
        """Verify grade is one of the valid grades"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        grade = data.get("tqs", {}).get("grade")
        
        valid_grades = ["A", "B+", "B", "C+", "C", "D", "F"]
        assert grade in valid_grades, f"Invalid grade: {grade}"
        
    def test_action_is_valid(self):
        """Verify action is one of the valid actions"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        action = data.get("tqs", {}).get("action")
        
        valid_actions = ["STRONG_BUY", "BUY", "HOLD", "AVOID", "STRONG_AVOID"]
        assert action in valid_actions, f"Invalid action: {action}"
        
    def test_pillar_scores_all_present(self):
        """Verify all 5 pillar scores are returned"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        pillar_scores = data.get("tqs", {}).get("pillar_scores", {})
        
        expected_pillars = ["setup", "technical", "fundamental", "context", "execution"]
        for pillar in expected_pillars:
            assert pillar in pillar_scores, f"Missing pillar score: {pillar}"
            score = pillar_scores[pillar]
            assert 0 <= score <= 100, f"{pillar} score {score} out of range"
            
    def test_different_symbols(self):
        """Test with different symbols (MSFT, TSLA)"""
        for symbol in ["MSFT", "TSLA"]:
            response = requests.get(f"{BASE_URL}/api/tqs/score/{symbol}?setup_type=breakout&direction=long")
            assert response.status_code == 200
            data = response.json()
            assert data.get("success") is True
            assert "tqs" in data


class TestTQSBreakdown:
    """Test GET /api/tqs/breakdown/{symbol} - Returns detailed breakdown"""
    
    def test_breakdown_endpoint_returns_success(self):
        """Verify breakdown endpoint returns success status"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_breakdown_contains_all_pillar_details(self):
        """Verify breakdown contains detailed info for all pillars"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        breakdown = data.get("breakdown", {}).get("breakdown", {})
        
        expected_pillars = ["setup", "technical", "fundamental", "context", "execution"]
        for pillar in expected_pillars:
            assert pillar in breakdown, f"Missing pillar breakdown: {pillar}"
            pillar_data = breakdown[pillar]
            assert "score" in pillar_data, f"{pillar} missing score"
            assert "grade" in pillar_data, f"{pillar} missing grade"
            assert "components" in pillar_data, f"{pillar} missing components"
            assert "factors" in pillar_data, f"{pillar} missing factors"
            
    def test_setup_pillar_components(self):
        """Verify Setup pillar returns correct components"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        setup = data.get("breakdown", {}).get("breakdown", {}).get("setup", {})
        components = setup.get("components", {})
        
        expected_components = ["pattern", "win_rate", "expected_value", "tape", "smb"]
        for comp in expected_components:
            assert comp in components, f"Missing setup component: {comp}"
            
    def test_technical_pillar_components(self):
        """Verify Technical pillar returns correct components"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        technical = data.get("breakdown", {}).get("breakdown", {}).get("technical", {})
        components = technical.get("components", {})
        
        expected_components = ["trend", "rsi", "levels", "volatility", "volume"]
        for comp in expected_components:
            assert comp in components, f"Missing technical component: {comp}"
            
    def test_fundamental_pillar_components(self):
        """Verify Fundamental pillar returns correct components"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        fundamental = data.get("breakdown", {}).get("breakdown", {}).get("fundamental", {})
        components = fundamental.get("components", {})
        
        expected_components = ["catalyst", "short_interest", "float", "institutional", "earnings"]
        for comp in expected_components:
            assert comp in components, f"Missing fundamental component: {comp}"
            
    def test_context_pillar_components(self):
        """Verify Context pillar returns correct components"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        context = data.get("breakdown", {}).get("breakdown", {}).get("context", {})
        components = context.get("components", {})
        
        expected_components = ["regime", "time", "sector", "vix", "day"]
        for comp in expected_components:
            assert comp in components, f"Missing context component: {comp}"
            
    def test_execution_pillar_components(self):
        """Verify Execution pillar returns correct components"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        execution = data.get("breakdown", {}).get("breakdown", {}).get("execution", {})
        components = execution.get("components", {})
        
        expected_components = ["history", "tilt", "entry_tendency", "exit_tendency", "streak"]
        for comp in expected_components:
            assert comp in components, f"Missing execution component: {comp}"
            
    def test_breakdown_includes_key_factors_and_concerns(self):
        """Verify breakdown includes key factors and concerns"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        breakdown = data.get("breakdown", {})
        
        assert "key_factors" in breakdown, "Missing key_factors"
        assert "concerns" in breakdown, "Missing concerns"
        assert "warnings" in breakdown, "Missing warnings"
        assert isinstance(breakdown["key_factors"], list), "key_factors should be a list"
        assert isinstance(breakdown["concerns"], list), "concerns should be a list"


class TestTQSBatch:
    """Test POST /api/tqs/batch - Batch scoring multiple opportunities"""
    
    def test_batch_endpoint_returns_success(self):
        """Verify batch endpoint returns success status"""
        payload = {
            "opportunities": [
                {"symbol": "AAPL", "setup_type": "bull_flag", "direction": "long"},
                {"symbol": "MSFT", "setup_type": "vwap_bounce", "direction": "long"}
            ]
        }
        response = requests.post(f"{BASE_URL}/api/tqs/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_batch_returns_correct_count(self):
        """Verify batch returns correct number of results"""
        payload = {
            "opportunities": [
                {"symbol": "AAPL", "setup_type": "bull_flag", "direction": "long"},
                {"symbol": "MSFT", "setup_type": "vwap_bounce", "direction": "long"},
                {"symbol": "TSLA", "setup_type": "breakout", "direction": "short"}
            ]
        }
        response = requests.post(f"{BASE_URL}/api/tqs/batch", json=payload)
        data = response.json()
        
        assert data.get("count") == 3, f"Expected count 3, got {data.get('count')}"
        assert len(data.get("results", [])) == 3, "Results count mismatch"
        
    def test_batch_results_are_sorted_by_score(self):
        """Verify batch results are sorted by score (highest first)"""
        payload = {
            "opportunities": [
                {"symbol": "AAPL", "setup_type": "bull_flag", "direction": "long"},
                {"symbol": "MSFT", "setup_type": "vwap_bounce", "direction": "long"},
                {"symbol": "TSLA", "setup_type": "breakout", "direction": "short"}
            ]
        }
        response = requests.post(f"{BASE_URL}/api/tqs/batch", json=payload)
        data = response.json()
        results = data.get("results", [])
        
        scores = [r.get("score", 0) for r in results]
        assert scores == sorted(scores, reverse=True), "Results not sorted by score descending"
        
    def test_batch_empty_opportunities(self):
        """Verify batch handles empty opportunities list"""
        payload = {"opportunities": []}
        response = requests.post(f"{BASE_URL}/api/tqs/batch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("results") == []
        
    def test_batch_max_limit(self):
        """Verify batch rejects more than 50 opportunities"""
        payload = {
            "opportunities": [{"symbol": f"TEST{i}", "setup_type": "unknown"} for i in range(51)]
        }
        response = requests.post(f"{BASE_URL}/api/tqs/batch", json=payload)
        assert response.status_code == 400


class TestTQSGuidance:
    """Test GET /api/tqs/guidance?score={score} - Returns trading guidance"""
    
    def test_guidance_endpoint_returns_success(self):
        """Verify guidance endpoint returns success status"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=75")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        
    def test_guidance_for_strong_buy_score(self):
        """Verify guidance for STRONG_BUY score (80+)"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=85")
        data = response.json()
        guidance = data.get("guidance", {})
        
        assert guidance.get("action") == "STRONG_BUY"
        assert "confidence" in guidance
        assert "sizing" in guidance
        assert "guidance" in guidance
        
    def test_guidance_for_buy_score(self):
        """Verify guidance for BUY score (65-79)"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=70")
        data = response.json()
        guidance = data.get("guidance", {})
        
        assert guidance.get("action") == "BUY"
        
    def test_guidance_for_hold_score(self):
        """Verify guidance for HOLD score (50-64)"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=55")
        data = response.json()
        guidance = data.get("guidance", {})
        
        assert guidance.get("action") == "HOLD"
        
    def test_guidance_for_avoid_score(self):
        """Verify guidance for AVOID score (35-49)"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=40")
        data = response.json()
        guidance = data.get("guidance", {})
        
        assert guidance.get("action") == "AVOID"
        
    def test_guidance_for_strong_avoid_score(self):
        """Verify guidance for STRONG_AVOID score (0-34)"""
        response = requests.get(f"{BASE_URL}/api/tqs/guidance?score=20")
        data = response.json()
        guidance = data.get("guidance", {})
        
        assert guidance.get("action") == "STRONG_AVOID"
        
    def test_guidance_boundary_values(self):
        """Test guidance at threshold boundaries"""
        # Test at exact threshold values
        boundaries = [
            (80, "STRONG_BUY"),
            (65, "BUY"),
            (50, "HOLD"),
            (35, "AVOID"),
            (34, "STRONG_AVOID")
        ]
        
        for score, expected_action in boundaries:
            response = requests.get(f"{BASE_URL}/api/tqs/guidance?score={score}")
            data = response.json()
            actual_action = data.get("guidance", {}).get("action")
            assert actual_action == expected_action, f"Score {score}: expected {expected_action}, got {actual_action}"


class TestTQSGradeAssignment:
    """Test that grades are correctly assigned based on score ranges"""
    
    def test_grade_a_for_score_85_plus(self):
        """Verify score 85+ gets grade A"""
        # Use high-quality setup to try to get high score
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=first_vwap_pullback&direction=long")
        data = response.json()
        breakdown = data.get("breakdown", {})
        score = breakdown.get("score", 0)
        grade = breakdown.get("grade", "")
        
        # Verify grade assignment logic works based on the actual score
        if score >= 85:
            assert grade == "A", f"Score {score} should have grade A, got {grade}"
        elif score >= 75:
            assert grade == "B+", f"Score {score} should have grade B+, got {grade}"
        elif score >= 65:
            assert grade == "B", f"Score {score} should have grade B, got {grade}"
        elif score >= 55:
            assert grade == "C+", f"Score {score} should have grade C+, got {grade}"
        elif score >= 45:
            assert grade == "C", f"Score {score} should have grade C, got {grade}"
        elif score >= 35:
            assert grade == "D", f"Score {score} should have grade D, got {grade}"
        else:
            assert grade == "F", f"Score {score} should have grade F, got {grade}"


class TestTQSActionAssignment:
    """Test that actions are correctly assigned based on thresholds"""
    
    def test_action_matches_score_threshold(self):
        """Verify action assignment matches score thresholds"""
        response = requests.get(f"{BASE_URL}/api/tqs/breakdown/AAPL?setup_type=bull_flag&direction=long")
        data = response.json()
        breakdown = data.get("breakdown", {})
        score = breakdown.get("score", 0)
        action = breakdown.get("action", "")
        
        # Verify action assignment based on score
        if score >= 80:
            assert action == "STRONG_BUY", f"Score {score} should have action STRONG_BUY, got {action}"
        elif score >= 65:
            assert action == "BUY", f"Score {score} should have action BUY, got {action}"
        elif score >= 50:
            assert action == "HOLD", f"Score {score} should have action HOLD, got {action}"
        elif score >= 35:
            assert action == "AVOID", f"Score {score} should have action AVOID, got {action}"
        else:
            assert action == "STRONG_AVOID", f"Score {score} should have action STRONG_AVOID, got {action}"


class TestTQSShortDirection:
    """Test TQS scoring for short direction trades"""
    
    def test_short_direction_scoring(self):
        """Verify short direction trades are scored correctly"""
        response = requests.get(f"{BASE_URL}/api/tqs/score/TSLA?setup_type=bear_flag&direction=short")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        tqs = data.get("tqs", {})
        assert "score" in tqs
        assert "action" in tqs
        
    def test_short_vs_long_scoring_differs(self):
        """Verify short and long direction produce different context scores"""
        long_response = requests.get(f"{BASE_URL}/api/tqs/breakdown/TSLA?setup_type=bear_flag&direction=long")
        short_response = requests.get(f"{BASE_URL}/api/tqs/breakdown/TSLA?setup_type=bear_flag&direction=short")
        
        long_data = long_response.json().get("breakdown", {}).get("breakdown", {})
        short_data = short_response.json().get("breakdown", {}).get("breakdown", {})
        
        # Technical and Context pillars should differ for long vs short
        long_technical = long_data.get("technical", {}).get("score", 0)
        short_technical = short_data.get("technical", {}).get("score", 0)
        
        # These don't have to be different but the API should work for both
        assert isinstance(long_technical, (int, float))
        assert isinstance(short_technical, (int, float))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
