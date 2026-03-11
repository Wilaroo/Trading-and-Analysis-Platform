"""
Test Enhanced Scanner IB Data Priority
Verifies that the scanner correctly prioritizes IB pushed data over Alpaca
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone


class TestScannerIBDataPriority:
    """Tests for scanner's IB data prioritization"""
    
    def test_get_ib_quote_when_connected(self):
        """Test that _get_ib_quote returns IB data when pusher is connected"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        # Mock IB pusher data
        mock_quotes = {
            "AAPL": {
                "last": 185.50,
                "bid": 185.45,
                "ask": 185.55,
                "bidSize": 500,
                "askSize": 400,
                "volume": 50000000,
                "high": 186.00,
                "low": 184.50,
                "open": 185.00,
                "close": 184.00
            }
        }
        
        with patch('routers.ib.is_pusher_connected', return_value=True):
            with patch('routers.ib.get_pushed_quotes', return_value=mock_quotes):
                scanner = get_enhanced_scanner()
                quote = scanner._get_ib_quote('AAPL')
                
                assert quote is not None
                assert quote['symbol'] == 'AAPL'
                assert quote['price'] == 185.50
                assert quote['bid'] == 185.45
                assert quote['ask'] == 185.55
                assert quote['bid_size'] == 500
                assert quote['ask_size'] == 400
                assert quote['source'] == 'ib_pusher'
    
    def test_get_ib_quote_when_disconnected(self):
        """Test that _get_ib_quote returns None when pusher is disconnected"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        with patch('routers.ib.is_pusher_connected', return_value=False):
            scanner = get_enhanced_scanner()
            quote = scanner._get_ib_quote('AAPL')
            
            assert quote is None
    
    def test_get_ib_quote_for_missing_symbol(self):
        """Test that _get_ib_quote returns None for symbols not in IB data"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        mock_quotes = {"MSFT": {"last": 400.00}}  # AAPL not in quotes
        
        with patch('routers.ib.is_pusher_connected', return_value=True):
            with patch('routers.ib.get_pushed_quotes', return_value=mock_quotes):
                scanner = get_enhanced_scanner()
                quote = scanner._get_ib_quote('AAPL')
                
                assert quote is None
    
    def test_is_ib_connected(self):
        """Test _is_ib_connected helper method"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        # Test when connected
        with patch('routers.ib.is_pusher_connected', return_value=True):
            scanner = get_enhanced_scanner()
            assert scanner._is_ib_connected() is True
        
        # Test when disconnected
        with patch('routers.ib.is_pusher_connected', return_value=False):
            scanner = get_enhanced_scanner()
            assert scanner._is_ib_connected() is False
    
    def test_get_quote_with_ib_priority_uses_ib_when_available(self):
        """Test that _get_quote_with_ib_priority uses IB data first"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        mock_ib_quote = {
            "symbol": "AAPL",
            "price": 185.50,
            "source": "ib_pusher"
        }
        
        scanner = get_enhanced_scanner()
        
        # Mock _get_ib_quote to return IB data
        with patch.object(scanner, '_get_ib_quote', return_value=mock_ib_quote):
            quote = asyncio.get_event_loop().run_until_complete(
                scanner._get_quote_with_ib_priority('AAPL')
            )
            
            assert quote is not None
            assert quote['source'] == 'ib_pusher'
            assert quote['price'] == 185.50
    
    def test_get_quote_with_ib_priority_falls_back_to_alpaca(self):
        """Test that _get_quote_with_ib_priority falls back to Alpaca when IB unavailable"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        mock_alpaca_quote = {
            "symbol": "AAPL",
            "price": 185.30
        }
        
        scanner = get_enhanced_scanner()
        
        async def run_test():
            # Mock IB to return None, Alpaca to return quote
            with patch.object(scanner, '_get_ib_quote', return_value=None):
                with patch.object(scanner.alpaca_service, 'get_quote', 
                                new_callable=AsyncMock, return_value=mock_alpaca_quote):
                    return await scanner._get_quote_with_ib_priority('AAPL')
        
        quote = asyncio.get_event_loop().run_until_complete(run_test())
        
        assert quote is not None
        assert quote['price'] == 185.30
    
    def test_get_quote_with_ib_priority_handles_zero_ib_price(self):
        """Test fallback to Alpaca when IB returns 0 price"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        mock_ib_quote = {
            "symbol": "AAPL",
            "price": 0,  # Zero price means no valid data
            "source": "ib_pusher"
        }
        
        mock_alpaca_quote = {
            "symbol": "AAPL",
            "price": 185.30
        }
        
        scanner = get_enhanced_scanner()
        
        async def run_test():
            with patch.object(scanner, '_get_ib_quote', return_value=mock_ib_quote):
                with patch.object(scanner.alpaca_service, 'get_quote', 
                                new_callable=AsyncMock, return_value=mock_alpaca_quote):
                    return await scanner._get_quote_with_ib_priority('AAPL')
        
        quote = asyncio.get_event_loop().run_until_complete(run_test())
        
        # Should fall back to Alpaca because IB price is 0
        assert quote is not None
        assert quote['price'] == 185.30


class TestScannerIntegration:
    """Integration tests for scanner data flow"""
    
    def test_scanner_has_ib_helpers(self):
        """Test that scanner has all required IB helper methods"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        scanner = get_enhanced_scanner()
        
        # Check all helper methods exist
        assert hasattr(scanner, '_get_ib_quote')
        assert hasattr(scanner, '_is_ib_connected')
        assert hasattr(scanner, '_get_quote_with_ib_priority')
        
        # Check they are callable
        assert callable(scanner._get_ib_quote)
        assert callable(scanner._is_ib_connected)
        assert callable(scanner._get_quote_with_ib_priority)
    
    def test_scanner_volume_filter_config(self):
        """Test scanner volume filter configuration works"""
        from services.enhanced_scanner import get_enhanced_scanner
        
        scanner = get_enhanced_scanner()
        config = scanner.get_volume_filter_config()
        
        assert 'min_adv_general' in config
        assert 'min_adv_intraday' in config
        assert 'intraday_setups' in config
        assert config['min_adv_general'] >= 0
        assert config['min_adv_intraday'] >= 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

