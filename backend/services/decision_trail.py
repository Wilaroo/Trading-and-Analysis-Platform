"""
decision_trail.py — Cross-collection joins for the v19.28 Diagnostics
Decision Trail Explorer.

Operator wants to trace ONE setup from scanner alert → AI module votes
→ debate consensus → gate decision → bot action → outcome — without
grepping `bot_trades` + `sentcom_shadow_decisions` + `scanner_alerts`
+ `sentcom_thoughts` separately. This service is the data spine that
makes every other Diagnostics view (Module Scorecard, Funnel Monitor,
Counterfactual Playground, EOD Insight Stream) easier to build later.

Join key: `alert_id` (stamped by `enhanced_scanner.LiveAlert.id` and
carried through `BotTrade.alert_id` + `ShadowDecision.trade_id`). For
passed setups (no bot trade), the link is symbol + nearest-time-window.

This module is pure-Python, no IB, no LLM calls. All MongoDB queries
exclude `_id` to avoid BSON ObjectId serialisation issues.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Time-window matching for shadow → alert join ──────────────────────────
# When a `shadow_decisions` row has no `trade_id`, we still want to
# stitch it back to the originating scanner alert. Match on (symbol,
# trigger_time within ±N seconds of alert created_at).
_SHADOW_ALERT_TIME_WINDOW_SECONDS = 90


# ── Trail outcome derivation ──────────────────────────────────────────────
def _derive_outcome(trade: Optional[Dict[str, Any]], shadow: Optional[Dict[str, Any]]) -> str:
    """Single-word outcome label for the trail header chip.

    Priority: real bot trade > shadow forward-tracked > pending.
    """
    if trade:
        status = (trade.get("status") or "").lower()
        if status == "closed":
            pnl = trade.get("realized_pnl") or trade.get("pnl") or 0
            try:
                pnl_f = float(pnl)
            except (TypeError, ValueError):
                pnl_f = 0.0
            if pnl_f > 0:
                return "win"
            if pnl_f < 0:
                return "loss"
            return "scratch"
        return "open"
    if shadow:
        if shadow.get("outcome_tracked"):
            shadow_pnl = shadow.get("hypothetical_pnl") or 0
            try:
                pf = float(shadow_pnl)
            except (TypeError, ValueError):
                pf = 0.0
            if pf > 0:
                return "shadow_win"
            if pf < 0:
                return "shadow_loss"
            return "shadow_scratch"
        return "shadow_pending"
    return "unknown"


def _summarize_module_votes(shadow: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten the shadow decision's per-module results into a list of
    one row per module: {module, recommendation, confidence, reasoning}.

    Skips modules that didn't run on this decision so the UI shows only
    what was actually evaluated.
    """
    if not shadow:
        return []
    out: List[Dict[str, Any]] = []

    debate = shadow.get("debate_result") or {}
    if debate:
        out.append({
            "module": "debate",
            "recommendation": debate.get("consensus") or debate.get("verdict") or "",
            "confidence": debate.get("confidence", 0),
            "reasoning": (
                debate.get("summary")
                or debate.get("reasoning")
                or ""
            )[:240],
            "agents": debate.get("agents") or {},
        })

    risk = shadow.get("risk_assessment") or {}
    if risk:
        out.append({
            "module": "risk_council",
            "recommendation": risk.get("recommendation") or risk.get("decision") or "",
            "confidence": risk.get("confidence", 0),
            "reasoning": (risk.get("rationale") or risk.get("explanation") or "")[:240],
        })

    inst = shadow.get("institutional_context") or {}
    if inst:
        out.append({
            "module": "institutional",
            "recommendation": inst.get("flow_bias") or inst.get("recommendation") or "",
            "confidence": inst.get("confidence", 0),
            "reasoning": (inst.get("summary") or inst.get("reasoning") or "")[:240],
        })

    ts = shadow.get("timeseries_forecast") or {}
    if ts:
        out.append({
            "module": "timeseries",
            "recommendation": ts.get("direction") or ts.get("recommendation") or "",
            "confidence": ts.get("confidence", 0),
            "reasoning": (ts.get("summary") or ts.get("reasoning") or "")[:240],
        })
    return out


def _trade_key_for_alert(alert_id: str) -> Dict[str, Any]:
    """Mongo query that matches a `bot_trades` doc by alert_id field
    (multiple fallback names since the field has been spelled both
    `alert_id` and `scan_id` in older code paths)."""
    return {"$or": [
        {"alert_id": alert_id},
        {"scan_id": alert_id},
    ]}


# ── Trail builder ────────────────────────────────────────────────────────
def build_decision_trail(db, identifier: str) -> Optional[Dict[str, Any]]:
    """Build a full decision trail for `identifier`.

    `identifier` can be any of:
      - alert_id (from scanner)
      - trade_id (from bot_trades)
      - shadow_decision_id (from shadow_decisions)

    Returns a structured dict with sections:
      - alert: scanner_alerts row (or summary from in-memory _live_alerts)
      - shadow: shadow_decisions row + flattened module votes
      - trade: bot_trades row + close info
      - thoughts: relevant sentcom_thoughts entries (TTL 7d) for the
        symbol within the decision's time window
      - meta: { outcome, identifier_type, time_to_decision_s }

    Returns None if nothing matches.
    """
    if db is None or not identifier:
        return None

    trade: Optional[Dict[str, Any]] = None
    shadow: Optional[Dict[str, Any]] = None
    alert_summary: Optional[Dict[str, Any]] = None
    identifier_type: Optional[str] = None

    try:
        # Try as a bot trade ID first.
        trade = db["bot_trades"].find_one({"id": identifier}, {"_id": 0})
        if trade:
            identifier_type = "trade_id"
            alert_id = trade.get("alert_id") or trade.get("scan_id")
            if alert_id:
                shadow = db["shadow_decisions"].find_one(
                    {"trade_id": identifier}, {"_id": 0}
                ) or db["shadow_decisions"].find_one(
                    {"trade_id": alert_id}, {"_id": 0}
                )
        else:
            # Try as a shadow decision ID.
            shadow = db["shadow_decisions"].find_one({"id": identifier}, {"_id": 0})
            if shadow:
                identifier_type = "shadow_id"
                if shadow.get("trade_id"):
                    trade = db["bot_trades"].find_one(
                        {"id": shadow["trade_id"]}, {"_id": 0}
                    )
            else:
                # Treat as alert_id — match either bot_trade.alert_id
                # or shadow.trade_id (operator naming overlap).
                identifier_type = "alert_id"
                trade = db["bot_trades"].find_one(_trade_key_for_alert(identifier), {"_id": 0})
                if trade:
                    shadow = db["shadow_decisions"].find_one(
                        {"trade_id": trade.get("id")}, {"_id": 0}
                    ) or db["shadow_decisions"].find_one(
                        {"trade_id": identifier}, {"_id": 0}
                    )
                else:
                    # Pure shadow-only (passed setup, no fill) — match
                    # by trade_id field (where bot stamped the alert_id).
                    shadow = db["shadow_decisions"].find_one(
                        {"trade_id": identifier}, {"_id": 0}
                    )
    except Exception as e:
        logger.warning(f"build_decision_trail({identifier}) join failed: {e}")
        return None

    if not (trade or shadow):
        return None

    # ── Alert summary ────────────────────────────────────────────────
    # We don't have a `scanner_alerts` collection persisted on disk
    # (alerts live in `enhanced_scanner._live_alerts` in-memory). So we
    # synthesize an alert summary from the trade's `entry_context`
    # and / or the shadow's trigger info — these are the persisted
    # echoes of the original scanner alert.
    if trade and trade.get("entry_context"):
        ec = trade["entry_context"]
        alert_summary = {
            "alert_id": trade.get("alert_id") or trade.get("scan_id"),
            "symbol": trade.get("symbol"),
            "setup_type": trade.get("setup_type"),
            "scan_tier": ec.get("scan_tier"),
            "smb_grade": ec.get("smb_grade") or trade.get("smb_grade"),
            "quality_score": trade.get("quality_score"),
            "exit_rule": ec.get("exit_rule"),
            "trading_approach": ec.get("trading_approach"),
            "reasoning": ec.get("reasoning") or [],
            "scanned_at": trade.get("created_at") or trade.get("executed_at"),
        }
    elif shadow:
        alert_summary = {
            "alert_id": shadow.get("trade_id"),
            "symbol": shadow.get("symbol"),
            "setup_type": shadow.get("trigger_type"),
            "smb_grade": shadow.get("market_regime", ""),
            "quality_score": shadow.get("confidence_score"),
            "scanned_at": shadow.get("trigger_time"),
        }

    # ── Sentcom thoughts in the decision's time window ──────────────
    # 2026-05-04 v19.31.5 — three small fixes the operator's
    # "empty content for fired trades" report exposed:
    #   1. Case-insensitive symbol match. `_persist_thought` now
    #      normalizes the persisted symbol to upper-case (see
    #      sentcom_service.py); for legacy rows that slipped in with
    #      lowercase, fall back to a $regex match.
    #   2. Anchor prefers `executed_at` (when the trade fired) over
    #      `created_at` (when the row was first inserted, often
    #      during AI consultation seconds before the fill). Better
    #      centers the window on the actual decision.
    #   3. Skip rows with empty/None content — these are dedup
    #      sentinels or metadata-only events that render as blank
    #      lines in Trail Explorer.
    thoughts: List[Dict[str, Any]] = []
    try:
        symbol = (trade or shadow or {}).get("symbol")
        anchor_iso = (
            (trade or {}).get("executed_at")
            or (trade or {}).get("created_at")
            or (shadow or {}).get("trigger_time")
            or (shadow or {}).get("created_at")
        )
        if symbol and anchor_iso:
            anchor = anchor_iso
            if isinstance(anchor, str):
                anchor = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            window_start = (anchor - timedelta(minutes=30)).isoformat()
            window_end = (anchor + timedelta(minutes=120)).isoformat()
            sym_upper = symbol.upper()
            sym_lower = symbol.lower()
            thoughts = list(
                db["sentcom_thoughts"]
                .find(
                    {
                        "symbol": {"$in": [sym_upper, sym_lower, symbol]},
                        "timestamp": {"$gte": window_start, "$lte": window_end},
                        # Filter out empty / None content. Thoughts that
                        # exist only to drive a metadata-only stream
                        # event (e.g. dedup sentinels) carry empty
                        # `content` and shouldn't render as blank lines
                        # in the Trail Explorer.
                        "content": {"$nin": ["", None]},
                    },
                    {"_id": 0},
                    sort=[("timestamp", 1)],
                    limit=80,
                )
            )
    except Exception as thought_err:
        logger.debug(f"thoughts lookup failed for {identifier}: {thought_err}")

    # ── Meta computation ─────────────────────────────────────────────
    outcome = _derive_outcome(trade, shadow)
    time_to_decision_s = None
    try:
        if alert_summary and alert_summary.get("scanned_at") and trade and trade.get("executed_at"):
            sa = alert_summary["scanned_at"]
            if isinstance(sa, str):
                sa = datetime.fromisoformat(sa.replace("Z", "+00:00"))
            if sa.tzinfo is None:
                sa = sa.replace(tzinfo=timezone.utc)
            ea = trade["executed_at"]
            if isinstance(ea, str):
                ea = datetime.fromisoformat(ea.replace("Z", "+00:00"))
            if ea.tzinfo is None:
                ea = ea.replace(tzinfo=timezone.utc)
            time_to_decision_s = (ea - sa).total_seconds()
    except Exception:
        pass

    return {
        "identifier": identifier,
        "identifier_type": identifier_type,
        "alert": alert_summary,
        "shadow": shadow,
        "module_votes": _summarize_module_votes(shadow),
        "trade": trade,
        "thoughts": thoughts,
        "meta": {
            "outcome": outcome,
            "time_to_decision_s": time_to_decision_s,
            "has_trade": bool(trade),
            "has_shadow": bool(shadow),
            "has_thoughts": len(thoughts) > 0,
        },
    }


# ── Recent decisions list ────────────────────────────────────────────────
def list_recent_decisions(
    db,
    limit: int = 50,
    symbol: Optional[str] = None,
    setup: Optional[str] = None,
    outcome: Optional[str] = None,
    only_disagreements: bool = False,
) -> List[Dict[str, Any]]:
    """Return a paginated list of recent decisions across `bot_trades`
    and `shadow_decisions` for the Trail Explorer's left rail.

    Each row is the minimum needed to render a list item:
      {id, identifier_type, symbol, setup, outcome, scanned_at,
       has_trade, has_shadow, modules_summary}

    Filters:
      - `symbol`: case-insensitive exact match
      - `setup`: substring match on setup_type / trigger_type
      - `outcome`: 'win' | 'loss' | 'scratch' | 'open' | 'shadow_*'
      - `only_disagreements`: True → keep only rows where module
        votes disagreed (e.g. debate=BUY but bot didn't fire). Useful
        for "what setups did I miss" + "what did the bot fire that
        the AI didn't love."
    """
    if db is None:
        return []
    rows: List[Dict[str, Any]] = []

    base_filter: Dict[str, Any] = {}
    if symbol:
        base_filter["symbol"] = symbol.upper()

    try:
        trade_q = dict(base_filter)
        if setup:
            trade_q["setup_type"] = {"$regex": setup, "$options": "i"}
        trades = list(
            db["bot_trades"]
            .find(
                trade_q,
                {"_id": 0, "id": 1, "alert_id": 1, "symbol": 1,
                 "setup_type": 1, "status": 1, "smb_grade": 1,
                 "quality_score": 1, "executed_at": 1, "created_at": 1,
                 "realized_pnl": 1, "pnl": 1, "direction": 1, "shares": 1},
                sort=[("created_at", -1)],
                limit=limit * 2,
            )
        )
        for t in trades:
            outcome_label = _derive_outcome(t, None)
            if outcome and outcome_label != outcome:
                continue
            rows.append({
                "identifier": t.get("id"),
                "identifier_type": "trade_id",
                "symbol": t.get("symbol"),
                "setup": t.get("setup_type"),
                "outcome": outcome_label,
                "scanned_at": t.get("created_at") or t.get("executed_at"),
                "has_trade": True,
                "has_shadow": False,  # filled below in dedup pass
                "smb_grade": t.get("smb_grade"),
                "quality_score": t.get("quality_score"),
                "direction": t.get("direction"),
                "shares": t.get("shares"),
                "pnl": t.get("realized_pnl") or t.get("pnl") or 0,
                "modules_summary": "",
            })
    except Exception as e:
        logger.debug(f"list_recent_decisions trade query failed: {e}")

    try:
        shadow_q = dict(base_filter)
        if setup:
            shadow_q["trigger_type"] = {"$regex": setup, "$options": "i"}
        shadows = list(
            db["shadow_decisions"]
            .find(
                shadow_q,
                {"_id": 0, "id": 1, "trade_id": 1, "symbol": 1,
                 "trigger_type": 1, "trigger_time": 1, "was_executed": 1,
                 "outcome_tracked": 1, "hypothetical_pnl": 1,
                 "combined_recommendation": 1, "confidence_score": 1,
                 "modules_used": 1, "debate_result.consensus": 1,
                 "risk_assessment.recommendation": 1, "outcome": 1},
                sort=[("trigger_time", -1)],
                limit=limit * 2,
            )
        )
        for s in shadows:
            if s.get("was_executed"):
                # Skip — the matching trade row already covers this in
                # the `bot_trades` pass. The dedup below also handles it.
                continue
            outcome_label = _derive_outcome(None, s)
            if outcome and outcome_label != outcome:
                continue
            modules_used = s.get("modules_used") or []
            modules_summary = ", ".join(modules_used[:3])
            if only_disagreements:
                # Disagreement = one module said one thing, another said
                # the opposite. Cheapest proxy: combined_recommendation
                # disagrees with debate consensus. Keep simple for now.
                debate_consensus = (s.get("debate_result", {}) or {}).get("consensus")
                combined = s.get("combined_recommendation")
                if debate_consensus and combined and debate_consensus != combined:
                    pass  # disagreement — keep
                else:
                    continue
            rows.append({
                "identifier": s.get("id"),
                "identifier_type": "shadow_id",
                "symbol": s.get("symbol"),
                "setup": s.get("trigger_type"),
                "outcome": outcome_label,
                "scanned_at": s.get("trigger_time"),
                "has_trade": False,
                "has_shadow": True,
                "smb_grade": "",
                "quality_score": s.get("confidence_score"),
                "direction": "",
                "shares": 0,
                "pnl": s.get("hypothetical_pnl") or 0,
                "modules_summary": modules_summary,
            })
    except Exception as e:
        logger.debug(f"list_recent_decisions shadow query failed: {e}")

    # Sort merged set by scanned_at desc, cap at limit.
    def _sort_key(r):
        sa = r.get("scanned_at") or ""
        return sa if isinstance(sa, str) else ""
    rows.sort(key=_sort_key, reverse=True)
    return rows[:limit]


# ── Module scorecard aggregation ─────────────────────────────────────────
def _aggregate_vote_breakdown(db, cutoff_iso: str) -> Dict[str, Dict[str, Any]]:
    """v19.31.4 — per-module vote tally from raw shadow_decisions.

    Aggregates the four module sub-dicts (debate_result, risk_assessment,
    institutional_context, timeseries_forecast) into a per-module
    {long_votes, short_votes, hold_votes, total_votes, agreed_with_final,
    disagreement_rate} block. Lets the operator see "this module is
    bullish 80% of the time even though final consensus is bearish 70%
    of the time" — useful for spotting modules that anchor too hard on
    one direction.

    Returns:
      {
        "debate_agents":     { long_votes, short_votes, hold_votes,
                              agreed_with_final, total_votes,
                              disagreement_rate },
        "risk_manager":      { proceed_votes, reject_votes, reduce_votes,
                              total_votes, agreed_with_final,
                              disagreement_rate },
        "institutional":     { positive_votes, negative_votes, neutral_votes,
                              total_votes },
        "timeseries":        { up_votes, down_votes, neutral_votes,
                              total_votes, agreed_with_final,
                              disagreement_rate },
      }

    `agreed_with_final` only counts decisions where the module's vote
    direction matches the final `combined_recommendation` ('proceed'
    means positive direction agreement, 'pass' negative, 'reduce_size'
    is treated as positive-but-cautious). When a module is silent on a
    given decision (no sub-dict populated), it doesn't count toward
    that module's totals.
    """
    out: Dict[str, Dict[str, Any]] = {
        "debate_agents":   {"long_votes": 0, "short_votes": 0, "hold_votes": 0,
                            "total_votes": 0, "agreed_with_final": 0},
        "risk_manager":    {"proceed_votes": 0, "reject_votes": 0,
                            "reduce_votes": 0, "total_votes": 0,
                            "agreed_with_final": 0},
        "institutional":   {"positive_votes": 0, "negative_votes": 0,
                            "neutral_votes": 0, "total_votes": 0},
        "timeseries":      {"up_votes": 0, "down_votes": 0, "neutral_votes": 0,
                            "total_votes": 0, "agreed_with_final": 0},
    }
    try:
        cursor = db["shadow_decisions"].find(
            {"trigger_time": {"$gte": cutoff_iso}},
            {"_id": 0, "combined_recommendation": 1, "debate_result": 1,
             "risk_assessment": 1, "institutional_context": 1,
             "timeseries_forecast": 1},
        )
        for d in cursor:
            final_rec = (d.get("combined_recommendation") or "").lower()
            final_positive = final_rec in ("proceed", "reduce_size")

            # Debate agents
            debate = d.get("debate_result") or {}
            winner = (debate.get("winner") or "").lower()
            if winner:
                out["debate_agents"]["total_votes"] += 1
                if winner == "bull":
                    out["debate_agents"]["long_votes"] += 1
                    if final_positive:
                        out["debate_agents"]["agreed_with_final"] += 1
                elif winner == "bear":
                    out["debate_agents"]["short_votes"] += 1
                    if not final_positive:
                        out["debate_agents"]["agreed_with_final"] += 1
                else:  # tie / hold
                    out["debate_agents"]["hold_votes"] += 1
                    # hold doesn't agree-or-disagree with proceed/pass
                    # — counts as neutral

            # Risk manager
            risk = d.get("risk_assessment") or {}
            risk_rec = (risk.get("recommendation") or "").lower()
            if risk_rec:
                out["risk_manager"]["total_votes"] += 1
                if risk_rec in ("proceed", "approve", "ok"):
                    out["risk_manager"]["proceed_votes"] += 1
                    if final_positive:
                        out["risk_manager"]["agreed_with_final"] += 1
                elif risk_rec in ("reject", "block", "no"):
                    out["risk_manager"]["reject_votes"] += 1
                    if not final_positive:
                        out["risk_manager"]["agreed_with_final"] += 1
                elif risk_rec in ("reduce", "reduce_size", "caution"):
                    out["risk_manager"]["reduce_votes"] += 1
                    if final_positive:
                        out["risk_manager"]["agreed_with_final"] += 1

            # Institutional flow — purely informational, no agree counter
            inst = d.get("institutional_context") or {}
            flow = (inst.get("flow_signal") or "").lower()
            if flow:
                out["institutional"]["total_votes"] += 1
                if flow in ("bullish", "buying", "accumulating", "positive"):
                    out["institutional"]["positive_votes"] += 1
                elif flow in ("bearish", "selling", "distributing", "negative"):
                    out["institutional"]["negative_votes"] += 1
                else:
                    out["institutional"]["neutral_votes"] += 1

            # Timeseries forecast
            ts = d.get("timeseries_forecast") or {}
            direction = (ts.get("direction") or "").lower()
            if direction:
                out["timeseries"]["total_votes"] += 1
                if direction in ("up", "bullish", "long"):
                    out["timeseries"]["up_votes"] += 1
                    if final_positive:
                        out["timeseries"]["agreed_with_final"] += 1
                elif direction in ("down", "bearish", "short"):
                    out["timeseries"]["down_votes"] += 1
                    if not final_positive:
                        out["timeseries"]["agreed_with_final"] += 1
                else:
                    out["timeseries"]["neutral_votes"] += 1

        # Compute disagreement_rate per module (where it makes sense).
        for mod_key in ("debate_agents", "risk_manager", "timeseries"):
            total = out[mod_key]["total_votes"]
            agreed = out[mod_key]["agreed_with_final"]
            out[mod_key]["disagreement_rate"] = (
                round(100.0 * (1 - agreed / total), 1) if total > 0 else None
            )
        # Institutional doesn't have agree/disagree (it's a context
        # signal, not a vote on direction), so no disagreement_rate.
    except Exception as e:
        logger.warning(f"_aggregate_vote_breakdown failed: {e}")
        out["error"] = str(e)
    return out


def build_module_scorecard(db, days: int = 7) -> Dict[str, Any]:
    """Aggregate per-AI-module performance over the last `days`.

    Returns:
      {
        days, generated_at, modules: [
          { module, total_decisions, accuracy_rate, avg_pnl_when_followed,
            avg_pnl_when_ignored, current_weight, weight_trend, kill_candidate }
        ]
      }

    This is the data the Diagnostics > Module Scorecard tab renders.
    Source: existing `shadow_module_performance` collection (already
    populated by `learning_connectors_service`) augmented with weight
    info from `shadow_module_weights` if present.
    """
    out: Dict[str, Any] = {
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modules": [],
        "vote_breakdown": {},  # v19.31.4 — per-module raw vote tally
    }
    if db is None:
        return out
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        # v19.31.4 — fresh per-module vote breakdown from raw shadow_decisions.
        # The pre-aggregated `shadow_module_performance` collection only
        # tracks accuracy_rate; this surfaces the directional bias
        # operators can't get otherwise.
        out["vote_breakdown"] = _aggregate_vote_breakdown(db, cutoff_iso)

        # The shadow_tracker already maintains per-module accuracy
        # rolling stats. Pull the freshest doc per module.
        agg = list(
            db["shadow_module_performance"]
            .aggregate([
                {"$match": {"updated_at": {"$gte": cutoff.isoformat()}}},
                {"$sort": {"updated_at": -1}},
                {"$group": {
                    "_id": "$module",
                    "total_decisions": {"$first": "$total_decisions"},
                    "accuracy_rate": {"$first": "$accuracy_rate"},
                    "avg_pnl_when_followed": {"$first": "$avg_pnl_when_followed"},
                    "avg_pnl_when_ignored": {"$first": "$avg_pnl_when_ignored"},
                    "updated_at": {"$first": "$updated_at"},
                }},
            ])
        )
        # Pull current weights (if collection exists).
        weights_map: Dict[str, float] = {}
        try:
            for w in db["shadow_module_weights"].find({}, {"_id": 0}):
                if w.get("module"):
                    weights_map[w["module"]] = float(w.get("weight", 1.0))
        except Exception:
            pass

        for row in agg:
            module = row.get("_id")
            current_weight = weights_map.get(module, 1.0)
            acc = float(row.get("accuracy_rate", 0) or 0)
            apf = float(row.get("avg_pnl_when_followed", 0) or 0)
            api = float(row.get("avg_pnl_when_ignored", 0) or 0)
            # Kill candidate: accuracy < 50% AND followed P&L < ignored P&L
            # (module is actively losing money vs simply ignoring it).
            kill_candidate = acc < 50.0 and apf < api
            out["modules"].append({
                "module": module,
                "total_decisions": int(row.get("total_decisions", 0) or 0),
                "accuracy_rate": round(acc, 1),
                "avg_pnl_when_followed": round(apf, 2),
                "avg_pnl_when_ignored": round(api, 2),
                "current_weight": round(current_weight, 2),
                "kill_candidate": kill_candidate,
                "updated_at": row.get("updated_at"),
            })
    except Exception as e:
        logger.warning(f"build_module_scorecard failed: {e}")
        out["error"] = str(e)
    # Sort: kill candidates first (operator's eye drawn there), then
    # by total_decisions desc.
    out["modules"].sort(key=lambda m: (
        0 if m.get("kill_candidate") else 1,
        -m.get("total_decisions", 0),
    ))
    return out


# ── Funnel computation ──────────────────────────────────────────────────
def build_pipeline_funnel(db, days: int = 1) -> Dict[str, Any]:
    """Compute the scanner-emit → AI-passed → risk-passed → fired →
    winners funnel for the Diagnostics > Funnel Monitor stage.

    Pulled from existing collections — no new instrumentation needed:
      - emit count: shadow_decisions count (every alert logs a shadow)
      - AI-passed: shadow.combined_recommendation = 'proceed'
      - Risk-passed: shadow.risk_assessment.recommendation != 'REJECT'
      - Fired: shadow.was_executed == True  (canonical "AI green-lit
        AND bot actually placed an order"); we cross-check against
        bot_trades to surface drift.
      - Winners: bot_trades with realized_pnl > 0

    Returns the counts + drop-reason breakdown per stage.

    2026-05-04 v19.31.4 — fixed the smoking-gun bug where the funnel
    matched on `combined_recommendation in ('BUY', 'STRONG_BUY')` but
    the actual values are `'proceed'`/`'pass'`/`'reduce_size'` per
    `shadow_tracker.ShadowDecision.combined_recommendation` (line 46).
    Result: `ai_passed` was always 0, making the entire funnel useless.
    Now match against the real values + `was_executed` for fired.
    """
    out: Dict[str, Any] = {
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stages": [],
    }
    if db is None:
        return out
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        # Stage 1 — scanner emit (every shadow decision = 1 alert
        # the scanner emitted, regardless of whether bot took it).
        emitted = db["shadow_decisions"].count_documents({
            "trigger_time": {"$gte": cutoff_iso},
        })
        # Stage 2 — AI passed = the AI council combined to "proceed".
        # `combined_recommendation` is always lowercase per shadow_tracker
        # but defend against legacy uppercase rows just in case.
        ai_pass_match = {"$in": ["proceed", "PROCEED", "Proceed"]}
        ai_passed = db["shadow_decisions"].count_documents({
            "trigger_time": {"$gte": cutoff_iso},
            "combined_recommendation": ai_pass_match,
        })
        # Stage 3 — risk-council didn't veto.
        risk_passed = db["shadow_decisions"].count_documents({
            "trigger_time": {"$gte": cutoff_iso},
            "combined_recommendation": ai_pass_match,
            "risk_assessment.recommendation": {
                "$nin": ["REJECT", "reject", "Reject", "BLOCK", "block", "Block"],
            },
        })
        # Stage 4 — fired. Two ways to count this:
        #   (a) shadow rows with was_executed=True  ← AI green-lit AND
        #       bot actually placed an order
        #   (b) bot_trades rows created in window  ← canonical fill
        # In a healthy pipeline these match. When they diverge, it's
        # almost always: bot_trades > shadow.was_executed → the bot
        # bypassed the shadow logger (auto-execute on a high-priority
        # alert that skipped consultation). Surface BOTH so the
        # operator can spot drift.
        fired_via_shadow = db["shadow_decisions"].count_documents({
            "trigger_time": {"$gte": cutoff_iso},
            "was_executed": True,
        })
        fired_via_trades = db["bot_trades"].count_documents({
            "$or": [
                {"executed_at": {"$gte": cutoff_iso}},
                {"created_at": {"$gte": cutoff_iso}},
            ],
        })
        # Use the larger of the two as the "fired" count so the funnel
        # is monotonic (fired >= risk_passed never fails) and the drift
        # is exposed via metadata.
        fired = max(fired_via_shadow, fired_via_trades)
        # Stage 5 — winners (closed positive).
        winners = db["bot_trades"].count_documents({
            "$or": [
                {"executed_at": {"$gte": cutoff_iso}},
                {"created_at": {"$gte": cutoff_iso}},
            ],
            "status": "closed",
            "$and": [
                {"$or": [
                    {"realized_pnl": {"$gt": 0}},
                    {"pnl": {"$gt": 0}},
                ]},
            ],
        })

        out["stages"] = [
            {"stage": "emitted",     "count": emitted,     "label": "Scanner alerts"},
            {"stage": "ai_passed",   "count": ai_passed,   "label": "AI passed"},
            {"stage": "risk_passed", "count": risk_passed, "label": "Risk passed"},
            {
                "stage": "fired", "count": fired, "label": "Bot fired",
                "fired_via_shadow": fired_via_shadow,
                "fired_via_trades": fired_via_trades,
                "drift_warning": (
                    "shadow.was_executed and bot_trades disagree — bot may "
                    "be firing without consulting the AI council"
                    if abs(fired_via_shadow - fired_via_trades) > max(
                        2, int(0.1 * max(fired_via_shadow, fired_via_trades))
                    )
                    else None
                ),
            },
            {"stage": "winners",     "count": winners,     "label": "Winners"},
        ]
        # Compute conversion percentage between consecutive stages so
        # the UI can highlight unusual drops.
        for i in range(1, len(out["stages"])):
            prev = out["stages"][i - 1]["count"]
            curr = out["stages"][i]["count"]
            out["stages"][i]["conversion_pct"] = (
                round(curr / prev * 100, 1) if prev > 0 else None
            )
    except Exception as e:
        logger.warning(f"build_pipeline_funnel failed: {e}")
        out["error"] = str(e)
    return out


# ── Markdown export ────────────────────────────────────────────────────
def export_report_markdown(db, days: int = 1) -> str:
    """One-click markdown dump operator can paste back to Emergent
    for tuning suggestions. Compact — fits in an LLM context window
    even when `days=7`.

    Sections:
      1. Funnel (counts + conversion %)
      2. Module Scorecard (table)
      3. Top recent decisions (last 20, with outcome)
      4. Disagreements (last 10 — where modules diverged)

    Returns a markdown string.
    """
    if db is None:
        return "_(decision_trail: db not connected)_"

    funnel = build_pipeline_funnel(db, days=days)
    scorecard = build_module_scorecard(db, days=days)
    recent = list_recent_decisions(db, limit=20)
    disagreements = list_recent_decisions(db, limit=10, only_disagreements=True)

    lines: List[str] = []
    lines.append(f"# SentCom Diagnostics Report — last {days}d")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n")

    lines.append("## 1. Pipeline Funnel\n")
    lines.append("| Stage | Count | Conversion |")
    lines.append("|---|--:|--:|")
    for s in funnel.get("stages", []):
        conv = s.get("conversion_pct")
        conv_str = f"{conv}%" if conv is not None else "—"
        lines.append(f"| {s['label']} | {s['count']:,} | {conv_str} |")
    lines.append("")

    lines.append("## 2. Module Scorecard\n")
    lines.append("| Module | Decisions | Accuracy | P&L (followed) | P&L (ignored) | Weight | Kill? |")
    lines.append("|---|--:|--:|--:|--:|--:|:-:|")
    for m in scorecard.get("modules", []):
        kill = "🔴" if m.get("kill_candidate") else " "
        lines.append(
            f"| {m['module']} | {m['total_decisions']:,} | "
            f"{m['accuracy_rate']}% | ${m['avg_pnl_when_followed']:.2f} | "
            f"${m['avg_pnl_when_ignored']:.2f} | {m['current_weight']} | {kill} |"
        )
    lines.append("")

    lines.append("## 3. Recent Decisions (last 20)\n")
    lines.append("| Time | Symbol | Setup | Outcome | P&L | Source |")
    lines.append("|---|---|---|---|--:|---|")
    for r in recent:
        sa = (r.get("scanned_at") or "")[:19]
        src = "TRADE" if r.get("has_trade") else "SHADOW"
        lines.append(
            f"| {sa} | {r.get('symbol', '?')} | "
            f"{(r.get('setup') or '')[:30]} | {r.get('outcome')} | "
            f"${(r.get('pnl') or 0):.2f} | {src} |"
        )
    lines.append("")

    if disagreements:
        lines.append("## 4. Module Disagreements (last 10)\n")
        lines.append("| Time | Symbol | Setup | Modules |")
        lines.append("|---|---|---|---|")
        for r in disagreements:
            sa = (r.get("scanned_at") or "")[:19]
            lines.append(
                f"| {sa} | {r.get('symbol', '?')} | "
                f"{(r.get('setup') or '')[:30]} | "
                f"{r.get('modules_summary') or '—'} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("_Paste this into the chat for Emergent tuning suggestions._")
    return "\n".join(lines)
