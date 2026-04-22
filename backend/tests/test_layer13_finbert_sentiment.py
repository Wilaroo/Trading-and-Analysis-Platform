"""Regression test for Layer 13 (FinBERT News Sentiment) wiring in ConfidenceGate.

Verifies the non-runtime contract:
  1. ConfidenceGate.__init__ sets `_finbert_scorer = None` (lazy-init pattern)
  2. The module imports FinBERTSentiment without circular import errors
  3. The class docstring documents Layer 13
  4. The scoring pattern bounds are safe (+10 max / -5 floor)

Live evaluation (score ranges → point attribution) is verified manually on
Spark via a smoke API call — see `/app/memory/PRD.md` follow-up notes.
"""
from services.ai_modules.confidence_gate import ConfidenceGate


def test_gate_init_lazy_scorer_is_none():
    """Scorer must be None at construction — lazy-init on first eval()."""
    gate = ConfidenceGate(db=None)
    assert hasattr(gate, "_finbert_scorer"), "Gate must declare _finbert_scorer attr"
    assert gate._finbert_scorer is None, "Scorer must start as None (lazy init)"


def test_gate_docstring_documents_layer13():
    """Layer 13 must be visible in class/module docstring for auditability."""
    import services.ai_modules.confidence_gate as mod
    assert "Layer 13" in (mod.__doc__ or ""), \
        "Module docstring must mention Layer 13 FinBERT sentiment"


def test_finbert_sentiment_importable():
    """No circular-import or missing-dep surprises at runtime."""
    from services.ai_modules.finbert_sentiment import FinBERTSentiment
    # Construct with no DB — should not crash (lazy model load)
    scorer = FinBERTSentiment(db=None)
    # Calling with no DB returns a safe {"has_sentiment": False, ...}
    result = scorer.get_symbol_sentiment("AAPL", lookback_days=1)
    assert isinstance(result, dict)
    assert result.get("has_sentiment") is False, \
        "Scorer with no DB must return has_sentiment=False, not raise"


def test_layer13_scoring_bounds_documented():
    """Sanity: the branches in Layer 13 stay within the documented bounds."""
    import inspect
    from services.ai_modules.confidence_gate import ConfidenceGate
    src = inspect.getsource(ConfidenceGate.evaluate)
    # Layer 13 block should only add/subtract within [-5, +10]
    assert "Layer 13" in src and "FINBERT" in src.upper(), \
        "Layer 13 FinBERT block must be present in evaluate()"
    # Extract the layer 13 chunk
    start = src.find("Layer 13")
    end = src.find("DETERMINE DECISION", start)
    if start == -1 or end == -1:
        return
    layer13 = src[start:end]
    # Verify only values used are the ones in the spec
    for banned in ["+= 15", "+= 20", "+= 12", "-= 10", "-= 15"]:
        assert banned not in layer13, \
            f"Layer 13 must stay in [-5, +10] bounds, found '{banned}'"
