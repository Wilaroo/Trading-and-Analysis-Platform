"""Local verification for v391 TQS descriptor + integrity changes.
Runs without IB; tolerates empty Mongo. Asserts display blocks + honesty fixes.
"""
import asyncio
import sys

from services.tqs.setup_quality import get_setup_quality_service
from services.tqs.technical_quality import get_technical_quality_service
from services.tqs.fundamental_quality import get_fundamental_quality_service
from services.tqs.context_quality import get_context_quality_service
from services.tqs.execution_quality import get_execution_quality_service


def _check_display(name, d):
    comps = d["components"]
    disp = d.get("display")
    assert disp, f"{name}: missing display block"
    for k in comps:
        assert k in disp, f"{name}: component '{k}' has no display entry"
        blk = disp[k]
        assert {"label", "verdict", "reading"} <= set(blk), f"{name}.{k}: bad block {blk}"
        assert blk["reading"], f"{name}.{k}: empty reading"
    print(f"  OK {name}: {len(comps)} sub-scores, all have display")
    return disp


async def main():
    fails = []

    # FUNDAMENTAL — no data => institutional must be honest 'No data', no fake (+)
    f = await get_fundamental_quality_service().calculate_score(symbol="ZZZZ", direction="long")
    fd = f.to_dict()
    disp = _check_display("fundamental", fd)
    if disp["institutional"]["verdict"] != "No data":
        fails.append(f"institutional verdict should be 'No data', got {disp['institutional']['verdict']}")
    if any("Good institutional ownership" in x for x in fd["factors"]):
        fails.append("FALSE POSITIVE institutional factor still present")
    print(f"    institutional => {disp['institutional']}")

    # EXECUTION — no trader profile => entry tendency honest, score 50, no 'Excellent'
    e = await get_execution_quality_service().calculate_score(symbol="ZZZZ", setup_type="trend_continuation", direction="long")
    ed = e.to_dict()
    disp = _check_display("execution", ed)
    if ed["components"]["entry_tendency"] != 50:
        fails.append(f"entry_tendency should be 50 when absent, got {ed['components']['entry_tendency']}")
    if disp["entry_tendency"]["verdict"] != "No data":
        fails.append(f"entry_tendency verdict should be 'No data', got {disp['entry_tendency']['verdict']}")
    if any("Excellent entry execution" in x for x in ed["factors"]):
        fails.append("FALSE POSITIVE entry-execution factor still present")
    print(f"    entry_tendency => {disp['entry_tendency']}")

    # SETUP — EV proxy honesty
    s = await get_setup_quality_service().calculate_score(setup_type="trend_continuation", symbol="ZZZZ", risk_reward=1.4)
    sd = s.to_dict()
    disp = _check_display("setup", sd)
    if "no live expectancy" not in disp["expected_value"]["reading"]:
        fails.append(f"EV reading not honest: {disp['expected_value']['reading']}")
    print(f"    expected_value => {disp['expected_value']}")
    print(f"    pattern => {disp['pattern']}")

    # TECHNICAL
    t = await get_technical_quality_service().calculate_score(symbol="ZZZZ", direction="long", rsi=64, atr_percent=2.6, rvol=1.0)
    td = t.to_dict()
    disp = _check_display("technical", td)
    print(f"    rsi => {disp['rsi']}  volatility => {disp['volatility']}")

    # CONTEXT — VIX meaning + regime name + ai sub-score
    c = await get_context_quality_service().calculate_score(symbol="ZZZZ", direction="long", vix_level=16.6, market_regime="range_bound", ai_model_agrees=False, ai_model_confidence=0.52, ai_model_direction="down")
    cd = c.to_dict()
    disp = _check_display("context", cd)
    if "ai_model" not in cd["components"]:
        fails.append("ai_model sub-score not exposed in context components")
    print(f"    vix => {disp['vix']}")
    print(f"    regime => {disp['regime']}")
    print(f"    ai_model => {disp['ai_model']}")

    print()
    if fails:
        print("FAILURES:")
        for x in fails:
            print("  - " + x)
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
