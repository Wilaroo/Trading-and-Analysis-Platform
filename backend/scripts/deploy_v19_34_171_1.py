"""v19.34.171.1 — hotfix: scalp decay was passing wrong arg to close_trade.

v171 shipped with ``bot.close_trade(trade, reason=...)`` — but the
actual signature is ``bot.close_trade(trade_id: str, reason=...)``.
Every flatten attempt raised TypeError silently in the inner
``except Exception``. Net result: SCALP-DECAY never closed anything.

This patch resolves ``trade_id`` from the trade object before
calling ``close_trade``.

Idempotent.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PM = os.path.join(ROOT, "services", "position_manager.py")


OLD = '''            async def _decay_one(trade, age_min):
                symbol = getattr(trade, "symbol", "?")
                try:
                    if hasattr(bot, "_cancel_oca_for_trade"):
                        try:
                            await bot._cancel_oca_for_trade(trade)
                        except Exception as ce:
                            logger.debug(
                                f"[v19.34.171] OCA cancel failed for {symbol}: {ce}"
                            )
                    await asyncio.sleep(2.0)
                    if hasattr(bot, "close_trade"):
                        ok = await bot.close_trade(trade, reason="scalp_time_decay")
                        if ok:
                            logger.info(
                                f"[v19.34.171 SCALP-DECAY] flattened {symbol} "
                                f"(age={age_min:.1f}min)"
                            )
                        else:
                            logger.warning(
                                f"[v19.34.171 SCALP-DECAY] close_trade returned "
                                f"False for {symbol}"
                            )
                except Exception as e:
                    logger.warning(
                        f"[v19.34.171 SCALP-DECAY] flatten failed for "
                        f"{symbol}: {e}"
                    )'''


NEW = '''            async def _decay_one(trade, age_min):
                symbol = getattr(trade, "symbol", "?")
                # v19.34.171.1 \u2014 close_trade takes (trade_id, reason),
                # NOT (trade_obj, reason). v171 shipped with the wrong
                # signature \u2192 every flatten attempt raised silently.
                trade_id = (
                    getattr(trade, "id", None)
                    or getattr(trade, "trade_id", None)
                )
                if not trade_id:
                    logger.warning(
                        f"[v19.34.171 SCALP-DECAY] no trade_id resolvable "
                        f"for {symbol}; skipping"
                    )
                    return
                try:
                    if hasattr(bot, "_cancel_oca_for_trade"):
                        try:
                            await bot._cancel_oca_for_trade(trade)
                        except Exception as ce:
                            logger.debug(
                                f"[v19.34.171] OCA cancel failed for {symbol}: {ce}"
                            )
                    await asyncio.sleep(2.0)
                    if hasattr(bot, "close_trade"):
                        ok = await bot.close_trade(trade_id, reason="scalp_time_decay")
                        if ok:
                            logger.info(
                                f"[v19.34.171 SCALP-DECAY] flattened {symbol} "
                                f"(age={age_min:.1f}min)"
                            )
                        else:
                            logger.warning(
                                f"[v19.34.171 SCALP-DECAY] close_trade returned "
                                f"False for {symbol}"
                            )
                except Exception as e:
                    logger.warning(
                        f"[v19.34.171 SCALP-DECAY] flatten failed for "
                        f"{symbol}: {e}"
                    )'''


def main():
    print("v19.34.171.1 hotfix \u2014 close_trade signature")
    with open(PM, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.171.1 \u2014 close_trade takes (trade_id, reason)" in src:
        print("  - position_manager.py already on v171.1 \u2014 skipping")
        return
    if OLD not in src:
        print("ERROR: anchor not found in position_manager.py")
        sys.exit(2)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(PM, f"{PM}.bak.v171_1.{stamp}")
    src = src.replace(OLD, NEW, 1)
    with open(PM, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - patched")
    import ast
    ast.parse(open(PM).read())
    print("  - syntax check OK")
    print()
    print("git add -A && git commit -m 'v19.34.171.1: scalp decay close_trade signature fix' && git push")


if __name__ == "__main__":
    main()
