"""
WebSocket Training Commands Test Suite
======================================
Tests the WebSocket-based training commands that bypass HTTP connection pool saturation.

Features tested:
- train_setup: Train a specific setup model (e.g., MOMENTUM)
- train_setup_all: Train all setup models
- train_general: Train general timeframe models
- ping: Basic WebSocket connectivity
- subscribe: Symbol subscription (existing functionality)
"""

import pytest
import asyncio
import json
import os
import websockets
from urllib.parse import urlparse

# Get the backend URL from environment
BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://backend-boot-repair.preview.emergentagent.com')

def get_websocket_url():
    """Convert HTTP URL to WebSocket URL with /api/ws/quotes path"""
    parsed = urlparse(BACKEND_URL)
    ws_protocol = 'wss' if parsed.scheme == 'https' else 'ws'
    return f"{ws_protocol}://{parsed.netloc}/api/ws/quotes"


class TestWebSocketTrainingCommands:
    """Test WebSocket training commands"""
    
    @pytest.mark.asyncio
    async def test_websocket_connection(self):
        """Test basic WebSocket connection"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Connecting to WebSocket: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Should receive connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            print(f"[TEST] Received: {data}")
            assert data.get('type') == 'connected', f"Expected 'connected', got {data.get('type')}"
            print("[TEST] WebSocket connection successful")
    
    @pytest.mark.asyncio
    async def test_ping_action(self):
        """Test ping action returns pong"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing ping action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send ping
            await ws.send(json.dumps({'action': 'ping'}))
            
            # Should receive pong
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            print(f"[TEST] Ping response: {data}")
            assert data.get('type') == 'pong', f"Expected 'pong', got {data.get('type')}"
            print("[TEST] Ping/pong successful")
    
    @pytest.mark.asyncio
    async def test_subscribe_action(self):
        """Test subscribe action returns subscribed"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing subscribe action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send subscribe
            await ws.send(json.dumps({'action': 'subscribe', 'symbols': ['AAPL']}))
            
            # Should receive subscribed
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            print(f"[TEST] Subscribe response: {data}")
            assert data.get('type') == 'subscribed', f"Expected 'subscribed', got {data.get('type')}"
            print("[TEST] Subscribe action successful")
    
    @pytest.mark.asyncio
    async def test_train_setup_action(self):
        """Test train_setup action queues a job and returns train_queued"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing train_setup action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send train_setup command
            train_msg = {
                'action': 'train_setup',
                'setup_type': 'MOMENTUM',
                'bar_size': '1 day'
            }
            print(f"[TEST] Sending: {train_msg}")
            await ws.send(json.dumps(train_msg))
            
            # Should receive train_queued response
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(msg)
            print(f"[TEST] Train setup response: {data}")
            
            assert data.get('type') == 'train_queued', f"Expected 'train_queued', got {data.get('type')}"
            assert data.get('success') == True, f"Expected success=True, got {data.get('success')}"
            assert 'job_id' in data, "Expected job_id in response"
            assert data.get('setup_type') == 'MOMENTUM', f"Expected setup_type='MOMENTUM', got {data.get('setup_type')}"
            
            job_id = data.get('job_id')
            print(f"[TEST] train_setup successful - job_id: {job_id}")
            
            # Return job_id for cleanup
            return job_id
    
    @pytest.mark.asyncio
    async def test_train_setup_all_action(self):
        """Test train_setup_all action queues a job and returns train_queued"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing train_setup_all action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send train_setup_all command
            train_msg = {
                'action': 'train_setup_all',
                'bar_size': '1 day'
            }
            print(f"[TEST] Sending: {train_msg}")
            await ws.send(json.dumps(train_msg))
            
            # Should receive train_queued response
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(msg)
            print(f"[TEST] Train setup all response: {data}")
            
            assert data.get('type') == 'train_queued', f"Expected 'train_queued', got {data.get('type')}"
            assert data.get('success') == True, f"Expected success=True, got {data.get('success')}"
            assert 'job_id' in data, "Expected job_id in response"
            assert data.get('train_type') == 'setup_all', f"Expected train_type='setup_all', got {data.get('train_type')}"
            
            job_id = data.get('job_id')
            print(f"[TEST] train_setup_all successful - job_id: {job_id}")
            
            return job_id
    
    @pytest.mark.asyncio
    async def test_train_general_action_single(self):
        """Test train_general action with train_type='single' queues a job"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing train_general (single) action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send train_general command
            train_msg = {
                'action': 'train_general',
                'bar_size': '1 day',
                'train_type': 'single'
            }
            print(f"[TEST] Sending: {train_msg}")
            await ws.send(json.dumps(train_msg))
            
            # Should receive train_queued response
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(msg)
            print(f"[TEST] Train general response: {data}")
            
            assert data.get('type') == 'train_queued', f"Expected 'train_queued', got {data.get('type')}"
            assert data.get('success') == True, f"Expected success=True, got {data.get('success')}"
            assert 'job_id' in data, "Expected job_id in response"
            assert data.get('train_type') == 'single', f"Expected train_type='single', got {data.get('train_type')}"
            
            job_id = data.get('job_id')
            print(f"[TEST] train_general (single) successful - job_id: {job_id}")
            
            return job_id
    
    @pytest.mark.asyncio
    async def test_train_general_action_train_all(self):
        """Test train_general action with train_type='train-all' and all_timeframes=True"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing train_general (train-all) action on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            
            # Send train_general command with all_timeframes
            train_msg = {
                'action': 'train_general',
                'bar_size': 'all',
                'train_type': 'train-all',
                'all_timeframes': True
            }
            print(f"[TEST] Sending: {train_msg}")
            await ws.send(json.dumps(train_msg))
            
            # Should receive train_queued response
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(msg)
            print(f"[TEST] Train general (train-all) response: {data}")
            
            assert data.get('type') == 'train_queued', f"Expected 'train_queued', got {data.get('type')}"
            assert data.get('success') == True, f"Expected success=True, got {data.get('success')}"
            assert 'job_id' in data, "Expected job_id in response"
            assert data.get('train_type') == 'train-all', f"Expected train_type='train-all', got {data.get('train_type')}"
            
            job_id = data.get('job_id')
            print(f"[TEST] train_general (train-all) successful - job_id: {job_id}")
            
            return job_id
    
    @pytest.mark.asyncio
    async def test_websocket_url_includes_api_ws_quotes(self):
        """Verify WebSocket URL includes /api/ws/quotes path"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Verifying WebSocket URL: {ws_url}")
        
        assert '/api/ws/quotes' in ws_url, f"WebSocket URL should include /api/ws/quotes, got: {ws_url}"
        print(f"[TEST] WebSocket URL correctly includes /api/ws/quotes")
    
    @pytest.mark.asyncio
    async def test_multiple_commands_in_sequence(self):
        """Test sending multiple commands in sequence on same connection"""
        ws_url = get_websocket_url()
        print(f"\n[TEST] Testing multiple commands in sequence on: {ws_url}")
        
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            # Wait for connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'connected'
            print("[TEST] Connected")
            
            # 1. Send ping
            await ws.send(json.dumps({'action': 'ping'}))
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'pong'
            print("[TEST] Ping successful")
            
            # 2. Send subscribe
            await ws.send(json.dumps({'action': 'subscribe', 'symbols': ['AAPL', 'MSFT']}))
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'subscribed'
            print("[TEST] Subscribe successful")
            
            # 3. Send train_setup
            await ws.send(json.dumps({'action': 'train_setup', 'setup_type': 'SCALP', 'bar_size': '1 day'}))
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(msg)
            assert data.get('type') == 'train_queued'
            assert data.get('setup_type') == 'SCALP'
            print(f"[TEST] Train setup successful - job_id: {data.get('job_id')}")
            
            # 4. Send another ping to verify connection still works
            await ws.send(json.dumps({'action': 'ping'}))
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get('type') == 'pong'
            print("[TEST] Final ping successful")
            
            print("[TEST] All sequential commands successful")


# Run tests if executed directly
if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
