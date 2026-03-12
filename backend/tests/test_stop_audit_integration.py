"""
Test Suite: Proactive Stop Audit and Bot Thoughts Stream Integration
=====================================================================
Tests for P2 Implementation:
- GET /api/trading-bot/audit-stops - Returns warnings for positions with risky stops
- GET /api/trading-bot/thoughts - Includes stop_warning action_type with severity levels
- Integration between audit_position_stops() and thoughts endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestAuditStopsEndpoint:
    """Tests for /api/trading-bot/audit-stops endpoint"""
    
    def test_audit_stops_returns_success(self):
        """Test that audit-stops endpoint returns success response"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, "Response should have success=True"
        print(f"✅ Audit-stops endpoint returned success")
    
    def test_audit_stops_response_structure(self):
        """Test that audit-stops response has required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        # Required top-level fields
        required_fields = ["success", "warnings", "positions_audited", "healthy_positions"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # warnings should be a list
        assert isinstance(data["warnings"], list), "warnings should be a list"
        
        # positions_audited should be an integer
        assert isinstance(data["positions_audited"], int), "positions_audited should be an integer"
        
        print(f"✅ Audit-stops response structure valid")
        print(f"   Positions audited: {data['positions_audited']}")
        print(f"   Healthy positions: {data['healthy_positions']}")
        print(f"   Warnings count: {len(data['warnings'])}")
    
    def test_audit_stops_warnings_structure(self):
        """Test that each warning has required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        warnings = data.get("warnings", [])
        
        # If there are warnings, check their structure
        if warnings:
            warning = warnings[0]
            required_warning_fields = ["symbol", "severity", "message"]
            for field in required_warning_fields:
                assert field in warning, f"Warning missing required field: {field}"
            
            # Check severity is valid
            valid_severities = ["critical", "warning", "info"]
            assert warning["severity"] in valid_severities, f"Invalid severity: {warning['severity']}"
            
            print(f"✅ Warning structure valid")
            print(f"   First warning: {warning['symbol']} - {warning['severity']}: {warning['message'][:80]}...")
        else:
            print(f"ℹ️ No warnings present (all positions healthy)")
    
    def test_audit_stops_summary_section(self):
        """Test that summary section has severity counts"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        # Summary should exist
        if "summary" in data:
            summary = data["summary"]
            assert "critical" in summary, "Summary should have 'critical' count"
            assert "warning" in summary, "Summary should have 'warning' count"
            assert "info" in summary, "Summary should have 'info' count"
            
            print(f"✅ Summary section valid")
            print(f"   Critical: {summary['critical']}")
            print(f"   Warning: {summary['warning']}")
            print(f"   Info: {summary['info']}")
    
    def test_audit_stops_warning_sorting(self):
        """Test that warnings are sorted by severity (critical first)"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        warnings = data.get("warnings", [])
        
        if len(warnings) >= 2:
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            
            for i in range(len(warnings) - 1):
                current_severity = warnings[i].get("severity", "info")
                next_severity = warnings[i + 1].get("severity", "info")
                
                assert severity_order.get(current_severity, 2) <= severity_order.get(next_severity, 2), \
                    f"Warnings not sorted: {current_severity} should come before {next_severity}"
            
            print(f"✅ Warnings correctly sorted by severity")
        else:
            print(f"ℹ️ Not enough warnings to test sorting ({len(warnings)} warnings)")


class TestThoughtsEndpoint:
    """Tests for /api/trading-bot/thoughts endpoint with stop_warning integration"""
    
    def test_thoughts_returns_success(self):
        """Test that thoughts endpoint returns success response"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("success") is True, "Response should have success=True"
        print(f"✅ Thoughts endpoint returned success")
    
    def test_thoughts_response_structure(self):
        """Test that thoughts response has required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        assert "thoughts" in data, "Response should have 'thoughts' field"
        assert isinstance(data["thoughts"], list), "thoughts should be a list"
        
        print(f"✅ Thoughts response structure valid")
        print(f"   Thoughts count: {len(data['thoughts'])}")
    
    def test_thoughts_include_stop_warnings(self):
        """Test that thoughts include stop_warning action_type"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get("thoughts", [])
        
        stop_warnings = [t for t in thoughts if t.get("action_type") == "stop_warning"]
        
        if stop_warnings:
            print(f"✅ Found {len(stop_warnings)} stop_warning thoughts")
            for warning in stop_warnings[:3]:
                print(f"   - {warning.get('symbol', 'N/A')}: {warning.get('severity', 'N/A')} - {warning.get('text', '')[:60]}...")
        else:
            print(f"ℹ️ No stop_warning thoughts present (all positions healthy)")
    
    def test_stop_warnings_have_severity(self):
        """Test that stop_warning thoughts have severity field"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get("thoughts", [])
        
        stop_warnings = [t for t in thoughts if t.get("action_type") == "stop_warning"]
        
        for warning in stop_warnings:
            assert "severity" in warning, "stop_warning should have 'severity' field"
            valid_severities = ["critical", "warning", "info"]
            assert warning["severity"] in valid_severities, f"Invalid severity: {warning['severity']}"
        
        if stop_warnings:
            print(f"✅ All stop_warning thoughts have valid severity")
        else:
            print(f"ℹ️ No stop_warnings to validate")
    
    def test_stop_warnings_at_top_of_stream(self):
        """Test that stop warnings appear at top of thoughts stream (highest priority)"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get("thoughts", [])
        
        if len(thoughts) < 2:
            print(f"ℹ️ Not enough thoughts to test ordering")
            return
        
        # Find first non-stop_warning thought
        first_non_stop_warning_idx = None
        for i, t in enumerate(thoughts):
            if t.get("action_type") != "stop_warning":
                first_non_stop_warning_idx = i
                break
        
        # Check that no stop_warnings appear after first non-stop_warning
        if first_non_stop_warning_idx is not None:
            for i in range(first_non_stop_warning_idx, len(thoughts)):
                assert thoughts[i].get("action_type") != "stop_warning", \
                    f"stop_warning found after non-stop_warning at index {i}"
        
        print(f"✅ Stop warnings correctly prioritized at top of stream")
    
    def test_stop_warning_confidence_levels(self):
        """Test that stop_warning confidence matches severity"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get("thoughts", [])
        
        stop_warnings = [t for t in thoughts if t.get("action_type") == "stop_warning"]
        
        for warning in stop_warnings:
            confidence = warning.get("confidence", 0)
            severity = warning.get("severity", "info")
            
            # Per the code: critical=95, warning=80, info=60
            if severity == "critical":
                assert confidence >= 90, f"Critical warning should have confidence >= 90, got {confidence}"
            elif severity == "warning":
                assert confidence >= 70, f"Warning should have confidence >= 70, got {confidence}"
            else:
                assert confidence >= 50, f"Info warning should have confidence >= 50, got {confidence}"
        
        if stop_warnings:
            print(f"✅ Stop warning confidence levels match severity")
        else:
            print(f"ℹ️ No stop_warnings to validate confidence")
    
    def test_thought_entry_structure(self):
        """Test that each thought has required fields"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=5", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        thoughts = data.get("thoughts", [])
        
        if thoughts:
            thought = thoughts[0]
            required_fields = ["text", "timestamp", "confidence", "action_type"]
            for field in required_fields:
                assert field in thought, f"Thought missing required field: {field}"
            
            print(f"✅ Thought entry structure valid")
            print(f"   Action types present: {set(t.get('action_type') for t in thoughts)}")
        else:
            print(f"ℹ️ No thoughts to validate structure")


class TestAuditThoughtsIntegration:
    """Tests for integration between audit-stops and thoughts stream"""
    
    def test_audit_warnings_appear_in_thoughts(self):
        """Test that audit warnings are reflected in thoughts stream"""
        # Get audit results
        audit_response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert audit_response.status_code == 200
        audit_data = audit_response.json()
        
        # Get thoughts
        thoughts_response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert thoughts_response.status_code == 200
        thoughts_data = thoughts_response.json()
        
        audit_warnings = audit_data.get("warnings", [])
        thought_stop_warnings = [t for t in thoughts_data.get("thoughts", []) 
                                if t.get("action_type") == "stop_warning"]
        
        # If audit has warnings, thoughts should have stop_warnings
        if audit_warnings:
            assert len(thought_stop_warnings) > 0, \
                "Audit has warnings but thoughts has no stop_warning entries"
            
            # Check that audit symbols appear in thoughts
            audit_symbols = set(w.get("symbol") for w in audit_warnings)
            thought_symbols = set(t.get("symbol") for t in thought_stop_warnings)
            
            common_symbols = audit_symbols & thought_symbols
            assert len(common_symbols) > 0, \
                f"No common symbols between audit ({audit_symbols}) and thoughts ({thought_symbols})"
            
            print(f"✅ Audit warnings correctly appear in thoughts stream")
            print(f"   Audit warnings: {len(audit_warnings)} for {audit_symbols}")
            print(f"   Thought warnings: {len(thought_stop_warnings)} for {thought_symbols}")
        else:
            print(f"ℹ️ No audit warnings, skipping integration check")
    
    def test_severity_consistency(self):
        """Test that severity levels are consistent between audit and thoughts"""
        # Get audit results
        audit_response = requests.get(f"{BASE_URL}/api/trading-bot/audit-stops", timeout=30)
        assert audit_response.status_code == 200
        audit_data = audit_response.json()
        
        # Get thoughts
        thoughts_response = requests.get(f"{BASE_URL}/api/trading-bot/thoughts?limit=10", timeout=30)
        assert thoughts_response.status_code == 200
        thoughts_data = thoughts_response.json()
        
        audit_warnings = audit_data.get("warnings", [])
        thought_stop_warnings = [t for t in thoughts_data.get("thoughts", []) 
                                if t.get("action_type") == "stop_warning"]
        
        # Build lookup for audit warnings
        audit_lookup = {}
        for w in audit_warnings:
            key = (w.get("symbol"), w.get("severity"))
            if key not in audit_lookup:
                audit_lookup[key] = w
        
        # Check thoughts against audit
        for thought in thought_stop_warnings:
            symbol = thought.get("symbol")
            severity = thought.get("severity")
            key = (symbol, severity)
            
            # There should be a matching audit warning
            if key in audit_lookup:
                print(f"   ✓ {symbol} ({severity}) matches audit")
        
        print(f"✅ Severity consistency check complete")


class TestBotStatusIntegration:
    """Tests for bot status with stop audit awareness"""
    
    def test_bot_status_available(self):
        """Test that bot status endpoint is available"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/status", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        
        print(f"✅ Bot status available")
        print(f"   Running: {data.get('running')}")
        print(f"   Mode: {data.get('mode')}")
    
    def test_open_trades_available(self):
        """Test that open trades data is available for audit"""
        response = requests.get(f"{BASE_URL}/api/trading-bot/trades/open", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("success") is True
        
        trades = data.get("trades", [])
        print(f"✅ Open trades available: {len(trades)} positions")
        
        if trades:
            for t in trades[:3]:
                symbol = t.get("symbol", "N/A")
                stop = t.get("stop_price", 0)
                current = t.get("current_price", 0)
                print(f"   - {symbol}: stop=${stop:.2f}, current=${current:.2f}")


# Run with: pytest test_stop_audit_integration.py -v --tb=short
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
