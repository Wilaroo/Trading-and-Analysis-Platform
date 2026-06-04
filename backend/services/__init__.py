# Services package
#
# v19.34.84: lazy re-exports (PEP 562). Importing this package no longer
# eagerly pulls in finnhub / ai_modules / market_context / etc. Submodules
# load only on first attribute access. Keeps `from services import X`
# semantics identical for production callers; unblocks tests that only
# need a single submodule (e.g. quote_resub_watchdog) from being held
# hostage by unrelated peripheral deps.

__all__ = [
    'StockDataService', 'get_stock_service',
    'NotificationService', 'get_notification_service',
    'MarketContextService', 'get_market_context_service',
    'StrategyRecommendationService', 'get_strategy_recommendation_service',
    'TradeJournalService', 'get_trade_journal_service',
]

_LAZY_MAP = {
    'StockDataService':                  ('.stock_data',               'StockDataService'),
    'get_stock_service':                 ('.stock_data',               'get_stock_service'),
    'NotificationService':               ('.notifications',            'NotificationService'),
    'get_notification_service':          ('.notifications',            'get_notification_service'),
    'MarketContextService':              ('.market_context',           'MarketContextService'),
    'get_market_context_service':        ('.market_context',           'get_market_context_service'),
    'StrategyRecommendationService':     ('.strategy_recommendations', 'StrategyRecommendationService'),
    'get_strategy_recommendation_service':('.strategy_recommendations','get_strategy_recommendation_service'),
    'TradeJournalService':               ('.trade_journal',            'TradeJournalService'),
    'get_trade_journal_service':         ('.trade_journal',            'get_trade_journal_service'),
}


def __getattr__(name):
    if name in _LAZY_MAP:
        from importlib import import_module
        mod_name, attr = _LAZY_MAP[name]
        mod = import_module(mod_name, __name__)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY_MAP.keys()))
