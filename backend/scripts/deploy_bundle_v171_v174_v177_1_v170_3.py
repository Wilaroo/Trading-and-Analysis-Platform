"""v19.34.171 + v174 + v177.1 + v170.3 — BUNDLE deploy.

Four small patches shipped together:

  v19.34.170.3 — Gate routers/ib.py:get_quotes_batch fallback behind
                 ib_service connection status. Pure log-noise silencer
                 (Client 1 dormant on this DGX rig). Zero behavior change.

  v19.34.171   — Scalp Time Decay. New method
                 PositionManager.check_scalp_decay() + new scan-loop
                 hook _check_scalp_decay(). Closes SCALP-timeframe
                 positions open longer than SCALP_DECAY_MINUTES (60
                 default) via OCA cancel → 2s wait → MKT flatten.
                 Skips if entry is <60min from market close (EOD
                 handles those). Per operator: existing scalp
                 positions WILL be flattened on first restart if
                 they're already past the decay timer.

  v19.34.174   — historical_data_queue_service._auto_clear_stuck_items
                 default reduced from 10 → 3 min (aligns with worker
                 timeout). Stops the 7-min "claimed" zombie phase
                 that masked the 98 stuck-job pattern.

  v19.34.177.1 — Rewire trade_context_service, quality_service, and
                 tqs/fundamental_quality.py to read fundamentals via
                 unified_fundamentals_cache (Stage B activation).

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
F_IB = os.path.join(ROOT, "routers", "ib.py")
F_HQ = os.path.join(ROOT, "services", "historical_data_queue_service.py")
F_TC = os.path.join(ROOT, "services", "trade_context_service.py")
F_QS = os.path.join(ROOT, "services", "quality_service.py")
F_FQ = os.path.join(ROOT, "services", "tqs", "fundamental_quality.py")
F_PM = os.path.join(ROOT, "services", "position_manager.py")
F_TB = os.path.join(ROOT, "services", "trading_bot_service.py")


# ───────── v170.3 — routers/ib.py batch quotes gate ─────────
IB_OLD = '''            if missing:
                try:
                    ib_quotes = await _ib_service.get_quotes_batch(missing)
                    quotes.extend(ib_quotes)
                except Exception as e:
                    print(f"IB batch quotes error (fallback): {e}")'''

IB_NEW = '''            if missing:
                # v19.34.170.3 — gate behind connection status. Client 1
                # is dormant on this DGX rig (live quotes flow through
                # the pusher), so this fallback would otherwise log
                # `Not connected to IB for batch quotes` once per
                # request. Pure log-noise silencer; no behavior change.
                try:
                    _ib_status = _ib_service.get_connection_status() if _ib_service else None
                    if _ib_status and _ib_status.get("connected"):
                        ib_quotes = await _ib_service.get_quotes_batch(missing)
                        quotes.extend(ib_quotes)
                except Exception as e:
                    print(f"IB batch quotes error (fallback): {e}")'''


# ───────── v174 — auto_clear timeout: 10 → 3 min ─────────
HQ_OLD = '''    def _auto_clear_stuck_items(self, older_than_minutes: int = 10):
        """
        Automatically clear items stuck in 'claimed' status for too long.
        Called internally when checking progress.
        """
        from datetime import datetime, timedelta, timezone'''

HQ_NEW = '''    def _auto_clear_stuck_items(self, older_than_minutes: int = 3):
        """
        Automatically clear items stuck in 'claimed' status for too long.
        Called internally when checking progress.

        v19.34.174 — reduced default from 10 \u2192 3 min. Worker's
        ``get_request_result`` timeout is 180s (3 min). After that the
        worker abandons the wait, but the row stays "claimed" until
        this sweep fires. The 7-min gap between abandonment and
        auto-clear was masking real failures and causing the 98-stuck
        pile-up the operator saw on 2026-05-28. Aligning the sweep
        with the worker timeout means failures surface immediately.
        """
        from datetime import datetime, timedelta, timezone'''


# ───────── v177.1 — trade_context_service rewire ─────────
TC_OLD = '''        fundamentals = FundamentalContext()

        try:
            ib_connected = False
            if self._ib_service is not None:
                try:
                    status = self._ib_service.get_connection_status()
                    ib_connected = bool(status and status.get("connected"))
                except Exception as e:
                    logger.debug(f"IB status probe failed for {symbol}: {e}")

            if ib_connected:
                try:
                    ib_data = await self._ib_service.get_fundamentals(symbol)
                    if ib_data and ib_data.get(\'success\'):
                        fund = ib_data.get(\'data\', {}) or {}
                        fundamentals.short_interest_percent = fund.get(\'short_interest_percent\', 0.0)
                        fundamentals.float_shares = fund.get(\'float_shares\', 0)
                        fundamentals.institutional_ownership_percent = fund.get(\'institutional_ownership_percent\', 0.0)
                        fundamentals.pe_ratio = fund.get(\'pe_ratio\')
                        fundamentals.market_cap = fund.get(\'market_cap\')
                except ConnectionError as ce:
                    # Connection dropped between status probe and call.
                    logger.debug(f"IB went stale mid-fundamentals for {symbol}: {ce}")
                except Exception as e:
                    logger.debug(f"IB fundamentals call failed for {symbol}: {e}")

            # Fallback / supplement: Finnhub fundamentals (always
            # populated for valuation context, since IB\'s
            # ReportSnapshot XML isn\'t parsed by this codebase).
            if fundamentals.pe_ratio is None or fundamentals.market_cap is None:
                try:
                    from services.fundamental_data_service import get_fundamental_data_service
                    fund_svc = get_fundamental_data_service()
                    fdata = await fund_svc.get_fundamentals(symbol)
                    if fdata is not None:
                        if fundamentals.pe_ratio is None:
                            fundamentals.pe_ratio = fdata.pe_ratio
                        if fundamentals.market_cap is None:
                            # Finnhub returns market cap in millions; keep
                            # as-is to match the historical IB shape.
                            fundamentals.market_cap = fdata.market_cap
                except Exception as e:
                    logger.debug(f"Finnhub fundamentals fallback failed for {symbol}: {e}")

            # Check for upcoming earnings (DB lookup \u2014 independent of IB)
            if self._db is not None:
                earnings = self._check_earnings_proximity(symbol)
                if earnings:
                    fundamentals.earnings_days_away = earnings.get(\'days_away\')
                    fundamentals.earnings_score = earnings.get(\'score\', 0)
                    if fundamentals.earnings_days_away is not None and fundamentals.earnings_days_away <= 7:
                        fundamentals.has_catalyst = True
                        fundamentals.catalyst_type = "earnings"

        except Exception as e:
            logger.warning(f"Error capturing fundamental context for {symbol}: {e}")

        context.fundamentals = fundamentals'''

TC_NEW = '''        fundamentals = FundamentalContext()

        # v19.34.177.1 \u2014 route through unified_fundamentals_cache. The
        # cache handles IB-first \u2192 Finnhub fallback \u2192 Mongo persistence
        # \u2192 smart TTL (24h, 1h within earnings). Replaces the v170-era
        # duplicated logic that was inlined here.
        try:
            from services.unified_fundamentals_cache import get_cached_fundamentals
            cached = await get_cached_fundamentals(symbol)
            if cached:
                if cached.get("pe_ratio") is not None:
                    fundamentals.pe_ratio = cached.get("pe_ratio")
                if cached.get("market_cap") is not None:
                    fundamentals.market_cap = cached.get("market_cap")
                # IB ReportSnapshot doesn\'t expose short_interest, float,
                # or institutional %. They\'d need ReportsOwnership (paid
                # add-on) or a Finnhub-specific endpoint we don\'t call.
                # Leave as None \u2014 downstream consumers handle gracefully.
        except Exception as e:
            logger.debug(f"unified_fundamentals_cache lookup failed for {symbol}: {e}")

        try:
            # Check for upcoming earnings (DB lookup \u2014 independent of IB)
            if self._db is not None:
                earnings = self._check_earnings_proximity(symbol)
                if earnings:
                    fundamentals.earnings_days_away = earnings.get(\'days_away\')
                    fundamentals.earnings_score = earnings.get(\'score\', 0)
                    if fundamentals.earnings_days_away is not None and fundamentals.earnings_days_away <= 7:
                        fundamentals.has_catalyst = True
                        fundamentals.catalyst_type = "earnings"

        except Exception as e:
            logger.warning(f"Error capturing fundamental context for {symbol}: {e}")

        context.fundamentals = fundamentals'''


# ───────── v177.1 — quality_service rewire ─────────
QS_OLD = '''    async def _fetch_from_ib(self, symbol: str) -> Optional[QualityMetrics]:
        """Fetch fundamental data from Interactive Brokers.

        v19.34.170.1 \u2014 gate behind ``get_connection_status()`` so we
        don\'t trip the WARN "Not connected to IB" log on every alert
        when the legacy direct ib_insync socket is dormant (which is
        the normal steady-state on the DGX where live data flows
        through the IB pusher RPC). When IB is down we silently fall
        back to the next data source upstream.
        """
        if not self.ib_service:
            return None

        # Skip when the direct IB worker reports disconnected \u2014 every
        # other quality data source (FMP, Finnhub) is preferred anyway,
        # and the IB ReportSnapshot XML isn\'t parsed by this method.
        try:
            status = self.ib_service.get_connection_status()
            if not (status and status.get("connected")):
                return None
        except Exception:
            # If even the status probe fails, the socket is definitely down.
            return None

        try:
            fundamentals = await self.ib_service.get_fundamentals(symbol)

            if not fundamentals or fundamentals.get("error"):
                return None

            metrics = QualityMetrics(symbol=symbol.upper())
            metrics.data_source = "interactive_brokers"

            # IB provides limited fundamental data
            # Extract what\'s available
            if "market_cap" in fundamentals:
                # Can use market cap for relative comparisons
                pass

            metrics.data_quality = "low"  # IB fundamentals are limited
            return metrics

        except ConnectionError as ce:
            # Lost the socket between status probe and call \u2014 demote
            # to debug, no log spam.
            logger.debug(f"IB went stale mid-quality fetch for {symbol}: {ce}")
            return None
        except Exception as e:
            logger.warning(f"IB fundamentals fetch failed for {symbol}: {e}")
            return None'''

QS_NEW = '''    async def _fetch_from_ib(self, symbol: str) -> Optional[QualityMetrics]:
        """Fetch fundamental data from Interactive Brokers.

        v19.34.177.1 \u2014 now routes through ``unified_fundamentals_cache``
        which handles IB-first \u2192 Finnhub fallback \u2192 Mongo persistence
        \u2192 smart TTL. Replaces the v170.1 inline gate.
        """
        try:
            from services.unified_fundamentals_cache import get_cached_fundamentals
            cached = await get_cached_fundamentals(symbol)
        except Exception as e:
            logger.debug(f"unified_fundamentals_cache lookup failed for {symbol}: {e}")
            return None

        if not cached:
            return None

        metrics = QualityMetrics(symbol=symbol.upper())
        metrics.data_source = cached.get("source", "unified_cache")
        # We don\'t extract anything meaningful from IB fundamentals
        # here today \u2014 the original quality scoring uses yfinance for
        # ROE/debt/cashflow. Keep the cache hit as a low-quality signal.
        metrics.data_quality = "low"
        return metrics'''


# ───────── v177.1 — tqs/fundamental_quality rewire ─────────
FQ_OLD = '''        # Fetch fundamental data if not provided
        # v19.34.170.2 \u2014 gate behind ib_service connection status (Client 1
        # is dormant on this DGX rig) and fall back to Finnhub via
        # FundamentalDataService. Previously this called IB unconditionally,
        # got a ConnectionError, and the pillar silently defaulted to
        # short_interest=5%, float=100M, institutional=50% \u2192 ~50/100
        # neutral score on every single trade (15% of TQS = pure noise).
        ib_connected = False
        if self._ib_service is not None:
            try:
                status = self._ib_service.get_connection_status()
                ib_connected = bool(status and status.get("connected"))
            except Exception:
                ib_connected = False

        if ib_connected:
            try:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                if ib_data and ib_data.get("success"):
                    fund = ib_data.get("data", {}) or {}
                    if short_interest_pct is None:
                        short_interest_pct = fund.get("short_interest_percent")
                    if float_shares is None:
                        float_shares = fund.get("float_shares")
                    if institutional_pct is None:
                        institutional_pct = fund.get("institutional_ownership_percent")
            except ConnectionError:
                # Socket died between status probe and call.
                pass
            except Exception as e:
                logger.debug(f"IB fundamentals fetch failed for {symbol}: {e}")

        # Finnhub fallback for valuation context (pe_ratio / market_cap /
        # beta) \u2014 used by other pillars but also flagged here so the
        # catalyst/short-interest branch gets real data.
        if any(v is None for v in (short_interest_pct, float_shares, institutional_pct)):
            try:
                from services.fundamental_data_service import get_fundamental_data_service
                fund_svc = get_fundamental_data_service()
                fdata = await fund_svc.get_fundamentals(symbol)
                if fdata is not None:
                    # Finnhub doesn\'t expose short interest directly via the
                    # profile endpoint; we only fill the fields it does have.
                    # The catalyst/earnings sub-scores below still drive
                    # the pillar \u2014 the defaults below only kick in if BOTH
                    # IB and Finnhub fail.
                    pass
            except Exception as e:
                logger.debug(f"Finnhub fundamentals fallback failed for {symbol}: {e}")
                
        # Check earnings calendar'''

FQ_NEW = '''        # Fetch fundamental data if not provided
        # v19.34.177.1 \u2014 route through unified_fundamentals_cache. The
        # cache handles IB-first \u2192 Finnhub fallback \u2192 Mongo persistence
        # \u2192 smart TTL. Replaces the v170.2 inline gate + Finnhub stub.
        try:
            from services.unified_fundamentals_cache import get_cached_fundamentals
            cached = await get_cached_fundamentals(symbol)
            if cached:
                # IB ReportSnapshot doesn\'t expose short_interest / float /
                # institutional %, but the cache will eventually carry
                # them if a ReportsOwnership integration is added.
                if short_interest_pct is None:
                    short_interest_pct = cached.get("short_interest_percent")
                if float_shares is None:
                    float_shares = cached.get("float_shares")
                if institutional_pct is None:
                    institutional_pct = cached.get("institutional_ownership_percent")
        except Exception as e:
            logger.debug(f"unified_fundamentals_cache lookup failed for {symbol}: {e}")
                
        # Check earnings calendar'''


# ───────── v171 — Scalp decay: position_manager method + scan-loop hook ─────────
# (large insert) — read from the agent-sandbox source-of-truth
PM_MARKER = "    async def check_eod_close(self, bot: 'TradingBotService'):"
PM_INSERT_PREFIX = "    async def check_scalp_decay(self, bot: 'TradingBotService'):"

# We embed the full method text here. Kept compact to fit the deploy.
PM_NEW_METHOD = '''
    async def check_scalp_decay(self, bot: \'TradingBotService\'):
        """v19.34.171 \u2014 Scalp Time Decay.

        Auto-close any SCALP-timeframe position open longer than
        ``SCALP_DECAY_MINUTES`` (default 60). Sequence: cancel OCA \u2192
        wait 2s \u2192 MKT flatten. Skips if entry is <``SCALP_DECAY_MIN_TIME_TO_CLOSE``
        minutes (default 60) from market close \u2014 EOD will handle.

        Env tunables:
          SCALP_DECAY_ENABLED        \u2014 "1" (default) / "0" to disable
          SCALP_DECAY_MINUTES        \u2014 60
          SCALP_DECAY_MIN_TIME_TO_CLOSE \u2014 60
        """
        import os
        if os.environ.get("SCALP_DECAY_ENABLED", "1") != "1":
            return
        try:
            decay_minutes = float(os.environ.get("SCALP_DECAY_MINUTES", "60") or "60")
        except (TypeError, ValueError):
            decay_minutes = 60.0
        try:
            min_to_close = float(os.environ.get("SCALP_DECAY_MIN_TIME_TO_CLOSE", "60") or "60")
        except (TypeError, ValueError):
            min_to_close = 60.0

        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("US/Eastern")
            now_et = datetime.now(et)
            close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            mins_to_close = (close_et - now_et).total_seconds() / 60.0
        except Exception:
            mins_to_close = 999.0

        if mins_to_close <= min_to_close:
            return

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(minutes=decay_minutes)

        try:
            scalp_candidates = []
            for trade in list(bot.trades.values()):
                if getattr(trade, "timeframe", "") != TradeTimeframe.SCALP:
                    continue
                if getattr(trade, "status", "") not in (TradeStatus.OPEN, "open"):
                    continue
                ex = (
                    getattr(trade, "executed_at", None)
                    or getattr(trade, "entry_time", None)
                )
                if not ex:
                    continue
                if isinstance(ex, str):
                    try:
                        ex_dt = datetime.fromisoformat(ex.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                elif isinstance(ex, datetime):
                    ex_dt = ex if ex.tzinfo else ex.replace(tzinfo=timezone.utc)
                else:
                    continue
                if ex_dt < cutoff:
                    age_min = (now_utc - ex_dt).total_seconds() / 60.0
                    scalp_candidates.append((trade, age_min))

            if not scalp_candidates:
                return

            logger.info(
                f"[v19.34.171 SCALP-DECAY] {len(scalp_candidates)} scalp "
                f"position(s) past {decay_minutes:.0f}-min decay; flattening."
            )

            async def _decay_one(trade, age_min):
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
                    )

            await asyncio.gather(
                *(_decay_one(t, a) for t, a in scalp_candidates),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error(f"[v19.34.171 SCALP-DECAY] sweep failed: {e}")

'''


# ───────── v171 — scan loop hook ─────────
TB_LOOP_OLD = '''                # Check for EOD close on scalp/intraday trades \u2014 also
                # safety-critical during data-fills (an EOD scalp must
                # close even if the data-fill is still running).
                try:
                    await asyncio.wait_for(self._check_eod_close(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"\u26a0\ufe0f [TradingBot] _check_eod_close exceeded {_EOD_WALL_S}s budget \u2014 skipping this cycle")'''

TB_LOOP_NEW = '''                # Check for EOD close on scalp/intraday trades \u2014 also
                # safety-critical during data-fills (an EOD scalp must
                # close even if the data-fill is still running).
                try:
                    await asyncio.wait_for(self._check_eod_close(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"\u26a0\ufe0f [TradingBot] _check_eod_close exceeded {_EOD_WALL_S}s budget \u2014 skipping this cycle")

                # v19.34.171 \u2014 Scalp time decay (auto-close stale scalps).
                # Budget under the EOD wall \u2014 sweep is read-mostly,
                # only acts on positions past the decay timer.
                try:
                    await asyncio.wait_for(self._check_scalp_decay(), timeout=_EOD_WALL_S)
                except asyncio.TimeoutError:
                    print(f"\u26a0\ufe0f [TradingBot] _check_scalp_decay exceeded {_EOD_WALL_S}s budget \u2014 skipping this cycle")
                except Exception as _sd_err:
                    print(f"\u26a0\ufe0f [TradingBot] _check_scalp_decay error: {_sd_err}")'''


TB_DELEGATE_OLD = '''    async def _check_eod_close(self):
        """EOD auto-close \u2014 delegated to PositionManager module."""
        await self._position_manager.check_eod_close(self)'''

TB_DELEGATE_NEW = '''    async def _check_eod_close(self):
        """EOD auto-close \u2014 delegated to PositionManager module."""
        await self._position_manager.check_eod_close(self)

    async def _check_scalp_decay(self):
        """v19.34.171 \u2014 Scalp time decay \u2014 delegated to PositionManager."""
        await self._position_manager.check_scalp_decay(self)'''


def _backup(p):
    s = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = f"{p}.bak.bundle.{s}"
    shutil.copy2(p, d)
    return d


def _patch(path, old, new, marker, label):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if marker in src:
        print(f"  - {label}: already on this version \u2014 skipping")
        return False
    if old not in src:
        print(f"ERROR: anchor not found in {path} for {label}")
        sys.exit(2)
    _backup(path)
    src = src.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"  - {label}: patched")
    return True


def _insert_pm():
    with open(F_PM, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.171 \u2014 Scalp Time Decay" in src or "check_scalp_decay" in src:
        print("  - position_manager.py: scalp decay already present \u2014 skipping")
        return False
    if PM_MARKER not in src:
        print(f"ERROR: PM marker not found in {F_PM}")
        sys.exit(3)
    _backup(F_PM)
    src = src.replace(PM_MARKER, PM_NEW_METHOD + PM_MARKER, 1)
    with open(F_PM, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - position_manager.py: check_scalp_decay inserted")
    return True


def main():
    print("=" * 60)
    print("BUNDLE — v170.3 + v171 + v174 + v177.1")
    print("=" * 60)

    _patch(F_IB, IB_OLD, IB_NEW, "v19.34.170.3 \u2014 gate behind connection status", "ib.py (v170.3)")
    _patch(F_HQ, HQ_OLD, HQ_NEW, "v19.34.174 \u2014 reduced default from 10",     "historical_data_queue (v174)")
    _patch(F_TC, TC_OLD, TC_NEW, "v19.34.177.1 \u2014 route through unified_fundamentals_cache", "trade_context_service (v177.1)")
    _patch(F_QS, QS_OLD, QS_NEW, "v19.34.177.1 \u2014 now routes through ``unified_fundamentals_cache``", "quality_service (v177.1)")
    _patch(F_FQ, FQ_OLD, FQ_NEW, "v19.34.177.1 \u2014 route through unified_fundamentals_cache", "tqs/fundamental_quality (v177.1)")
    _insert_pm()
    _patch(F_TB, TB_LOOP_OLD, TB_LOOP_NEW, "v19.34.171 \u2014 Scalp time decay (auto-close stale scalps)", "trading_bot_service loop hook (v171)")
    _patch(F_TB, TB_DELEGATE_OLD, TB_DELEGATE_NEW, "v19.34.171 \u2014 Scalp time decay \u2014 delegated", "trading_bot_service delegate (v171)")

    print()
    # parse-check
    import ast
    for p in [F_IB, F_HQ, F_TC, F_QS, F_FQ, F_PM, F_TB]:
        with open(p, "r", encoding="utf-8") as f:
            ast.parse(f.read())
    print("syntax check: ALL OK")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'bundle: v170.3 + v171 + v174 + v177.1' && git push")
    print("  2. Restart backend (fire your .bat) BEFORE 3:45 PM ET")
    print("  3. Verify after restart:")
    print("     grep -c 'SCALP-DECAY' /tmp/backend.log         # scalp decay sweeps")
    print("     grep -c 'Not connected to IB' /tmp/backend.log # should stay flat")


if __name__ == "__main__":
    main()
