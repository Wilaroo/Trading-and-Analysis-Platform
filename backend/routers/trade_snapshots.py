"""
Trade Snapshots Router - API endpoints for chart snapshots with AI annotations.
All endpoints are sync def so FastAPI runs them in a thread pool,
avoiding event loop saturation from IB Gateway retries.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import base64
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trades/snapshots", tags=["trade-snapshots"])

# Initialized from server.py
snapshot_service = None
_assistant_service = None


def init_snapshot_service(service):
    global snapshot_service
    snapshot_service = service


def init_snapshot_assistant(assistant_service):
    global _assistant_service
    _assistant_service = assistant_service


class ExplainRequest(BaseModel):
    annotation_index: int = 0
    question: Optional[str] = None


@router.get("/{trade_id}")
def get_snapshot(trade_id: str, source: str = "bot"):
    """Get existing snapshot for a trade (returns metadata + base64 chart)."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap:
        return {"success": False, "error": "No snapshot found", "snapshot": None}

    return {"success": True, "snapshot": snap}


@router.get("/{trade_id}/image")
def get_snapshot_image(trade_id: str, source: str = "bot"):
    """Get just the chart image as a PNG file."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap or not snap.get("chart_image"):
        raise HTTPException(404, "No snapshot image found")

    image_bytes = base64.b64decode(snap["chart_image"])
    return Response(content=image_bytes, media_type="image/png")


@router.post("/{trade_id}/generate")
def generate_snapshot(trade_id: str, source: str = "bot"):
    """Generate (or regenerate) a snapshot for a specific trade. Runs sync to avoid event loop blocking."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    result = snapshot_service.generate_snapshot_sync(trade_id, source)
    return result


@router.post("/batch")
def batch_generate(limit: int = 50):
    """Generate snapshots for closed trades that don't have one yet. Runs sync."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    result = snapshot_service.batch_generate_sync(limit=limit)
    return {"success": True, **result}


@router.get("")
def list_snapshots(source: Optional[str] = None, limit: int = 50):
    """List existing snapshots (metadata only, no chart images)."""
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    query = {}
    if source:
        query["source"] = source

    snapshots = list(snapshot_service.snapshots_col.find(
        query,
        {"_id": 0, "chart_image": 0}  # Exclude heavy image data
    ).sort("generated_at", -1).limit(limit))

    return {"success": True, "snapshots": snapshots, "count": len(snapshots)}


@router.post("/{trade_id}/explain")
def explain_annotation(trade_id: str, request: ExplainRequest, source: str = "bot"):
    """
    Get an AI-powered explanation for a specific annotation on a trade snapshot.
    Uses Ollama/GPT-OSS to generate detailed reasoning.
    """
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap:
        raise HTTPException(404, "No snapshot found for this trade")

    annotations = snap.get("annotations", [])
    if request.annotation_index >= len(annotations):
        raise HTTPException(400, f"Annotation index {request.annotation_index} out of range (0-{len(annotations)-1})")

    annotation = annotations[request.annotation_index]

    # Build rich context from trade + annotation data
    trade_ctx = (
        f"Trade: {snap.get('symbol', '?')} | {snap.get('direction', '?').upper()} | "
        f"{snap.get('setup_type', '?')} | P&L: ${snap.get('pnl', 0):+.2f}\n"
        f"Entry: ${snap.get('entry_price', 0):.2f} at {snap.get('entry_time', '?')}\n"
        f"Exit: ${snap.get('exit_price', 0):.2f} at {snap.get('exit_time', '?')}\n"
        f"Close reason: {snap.get('close_reason', '?')}\n"
        f"Timeframe: {snap.get('timeframe', '?')}"
    )

    ann_ctx = (
        f"Annotation type: {annotation.get('type', '?')}\n"
        f"Label: {annotation.get('label', '?')}\n"
        f"Price: ${annotation.get('price', 0):.2f}\n"
        f"Time: {annotation.get('time', '?')}\n"
        f"Current reasons: {'; '.join(annotation.get('reasons', []))}"
    )

    all_annotations_ctx = "\n".join([
        f"  [{a['type']}] {a['label']} @ ${a.get('price', 0):.2f}: {'; '.join(a.get('reasons', [])[:2])}"
        for a in annotations
    ])

    user_question = request.question or f"Explain this {annotation.get('type', 'decision')} in detail"

    prompt = (
        f"You are an expert AI trading analyst reviewing a trade snapshot. "
        f"A trader is asking about a specific decision point on their trade chart.\n\n"
        f"TRADE CONTEXT:\n{trade_ctx}\n\n"
        f"ALL DECISION POINTS ON THIS TRADE:\n{all_annotations_ctx}\n\n"
        f"SPECIFIC ANNOTATION THE TRADER IS ASKING ABOUT:\n{ann_ctx}\n\n"
        f"TRADER'S QUESTION: {user_question}\n\n"
        f"Provide a detailed, insightful explanation. Include:\n"
        f"1. Why this decision was made at this specific price/time\n"
        f"2. What market conditions or signals supported it\n"
        f"3. Whether it was the right call given the outcome\n"
        f"4. What could have been done differently\n"
        f"Keep it conversational and educational. Use 'we' voice. 2-3 paragraphs max."
    )

    # Try to call AI via the assistant service
    explanation = _call_llm_sync(prompt, trade_ctx)

    return {
        "success": True,
        "explanation": explanation,
        "annotation": annotation,
        "trade_summary": {
            "symbol": snap.get("symbol"),
            "direction": snap.get("direction"),
            "setup_type": snap.get("setup_type"),
            "pnl": snap.get("pnl"),
            "entry_price": snap.get("entry_price"),
            "exit_price": snap.get("exit_price"),
        }
    }


@router.post("/{trade_id}/chat-context")
def get_chat_context(trade_id: str, request: ExplainRequest, source: str = "bot"):
    """
    Returns a pre-formatted context message for sending to the SentCom chat.
    The frontend can use this to pre-fill the chat bubble.
    """
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap:
        raise HTTPException(404, "No snapshot found")

    annotations = snap.get("annotations", [])
    annotation = annotations[request.annotation_index] if request.annotation_index < len(annotations) else None

    # Build a chat message that gives the SentCom AI full context
    ann_detail = ""
    if annotation:
        ann_detail = (
            f"I'm looking at the {annotation.get('type', '?')} annotation "
            f"({annotation.get('label', '?')}) at ${annotation.get('price', 0):.2f}. "
            f"The recorded reasons are: {'; '.join(annotation.get('reasons', []))}. "
        )

    chat_message = (
        f"I'm reviewing my {snap.get('symbol', '?')} {snap.get('direction', '?')} "
        f"{snap.get('setup_type', '?')} trade (P&L: ${snap.get('pnl', 0):+.2f}). "
        f"{ann_detail}"
        f"{request.question or 'Can you give me a deeper analysis of this decision?'}"
    )

    return {
        "success": True,
        "chat_message": chat_message,
        "trade_id": trade_id,
        "annotation_index": request.annotation_index,
    }


@router.post("/{trade_id}/hindsight")
def hindsight_analysis(trade_id: str, source: str = "bot"):
    """
    'What I'd Do Differently' — AI-powered hindsight analysis comparing
    the actual trade outcome against current model knowledge.
    """
    if not snapshot_service:
        raise HTTPException(500, "Snapshot service not initialized")

    snap = snapshot_service.get_snapshot(trade_id, source)
    if not snap:
        raise HTTPException(404, "No snapshot found for this trade")

    # Build hindsight data from DB
    hindsight_data = _build_hindsight_data(snap, snapshot_service.db)

    # Build LLM prompt
    prompt = _build_hindsight_prompt(snap, hindsight_data)

    # Get AI analysis
    ai_narrative = _call_llm_sync(prompt, "hindsight analysis")

    return {
        "success": True,
        "hindsight": {
            "narrative": ai_narrative,
            "data": hindsight_data,
            "trade_id": trade_id,
            "symbol": snap.get("symbol"),
            "setup_type": snap.get("setup_type"),
            "pnl": snap.get("pnl"),
        }
    }


def _build_hindsight_data(snap: dict, db) -> dict:
    """Build structured hindsight data from trade outcomes, gate logs, and similar trades."""
    setup_type = snap.get("setup_type", "")
    direction = snap.get("direction", "long")
    pnl = snap.get("pnl", 0)
    close_reason = snap.get("close_reason", "")

    data = {
        "trade_outcome": "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN",
        "pnl": pnl,
        "close_reason": close_reason,
    }

    # 1. Similar trades performance (same setup_type, same direction)
    similar_trades = list(db.strategy_performance.find(
        {"strategy": setup_type, "direction": direction},
        {"_id": 0, "realized_pnl": 1, "pnl_pct": 1, "quality_score": 1, "close_reason": 1, "risk_reward_ratio": 1}
    ).limit(100))

    if similar_trades:
        wins = [t for t in similar_trades if t.get("realized_pnl", 0) > 0]
        losses = [t for t in similar_trades if t.get("realized_pnl", 0) < 0]
        total = len(similar_trades)
        win_rate = len(wins) / total * 100 if total > 0 else 0
        avg_win = sum(t.get("realized_pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("realized_pnl", 0) for t in losses) / len(losses) if losses else 0
        avg_rr = sum(t.get("risk_reward_ratio", 0) for t in similar_trades if t.get("risk_reward_ratio")) / max(1, len([t for t in similar_trades if t.get("risk_reward_ratio")]))

        data["similar_trades"] = {
            "count": total,
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_risk_reward": round(avg_rr, 2),
            "common_close_reasons": _top_values([t.get("close_reason", "") for t in similar_trades if t.get("close_reason")]),
        }
    else:
        data["similar_trades"] = {"count": 0, "win_rate": 0}

    # 2. Recent gate decisions for this setup
    recent_gates = list(db.confidence_gate_log.find(
        {"setup_type": setup_type},
        {"_id": 0, "decision": 1, "confidence_score": 1, "reasoning": 1, "regime_state": 1, "trading_mode": 1}
    ).sort("timestamp", -1).limit(20))

    if recent_gates:
        decisions = [g.get("decision", "") for g in recent_gates]
        go_count = decisions.count("GO")
        reduce_count = decisions.count("REDUCE")
        skip_count = decisions.count("SKIP")
        avg_conf = sum(g.get("confidence_score", 0) for g in recent_gates) / len(recent_gates)
        latest_mode = recent_gates[0].get("trading_mode", "")
        latest_regime = recent_gates[0].get("regime_state", "")

        data["current_gate_stance"] = {
            "recent_decisions": {"GO": go_count, "REDUCE": reduce_count, "SKIP": skip_count},
            "avg_confidence": round(avg_conf, 1),
            "current_mode": latest_mode,
            "current_regime": latest_regime,
            "would_take_today": "GO" if avg_conf >= 65 else "REDUCE" if avg_conf >= 45 else "SKIP",
        }
    else:
        data["current_gate_stance"] = {"recent_decisions": {}, "avg_confidence": 0, "would_take_today": "NO DATA"}

    # 3. Learning loop feedback (trade_outcomes for this setup)
    outcomes = list(db.trade_outcomes.find(
        {"setup_type": setup_type},
        {"_id": 0, "outcome": 1, "pnl_percent": 1, "context": 1}
    ).limit(20))

    if outcomes:
        outcome_wins = len([o for o in outcomes if o.get("outcome") == "won"])
        outcome_total = len(outcomes)
        data["learning_loop"] = {
            "total_outcomes_tracked": outcome_total,
            "win_rate_from_outcomes": round(outcome_wins / outcome_total * 100, 1) if outcome_total > 0 else 0,
            "has_model_feedback": any(o.get("context", {}).get("model_prediction") for o in outcomes),
        }
    else:
        data["learning_loop"] = {"total_outcomes_tracked": 0}

    # 4. What specifically would change
    improvements = []
    sim_wr = data.get("similar_trades", {}).get("win_rate", 0)
    gate_stance = data.get("current_gate_stance", {})
    
    if pnl < 0:
        # Loss analysis
        if close_reason == "stop_loss" and data.get("similar_trades", {}).get("avg_risk_reward", 0) > 1.5:
            improvements.append("Stop may have been too tight — similar winning trades had avg R:R of {:.1f}".format(data["similar_trades"]["avg_risk_reward"]))
        if gate_stance.get("would_take_today") == "SKIP":
            improvements.append("Current gate would SKIP this setup — model has learned to be more selective here")
        elif gate_stance.get("would_take_today") == "REDUCE":
            improvements.append("Current gate would REDUCE position size — limiting exposure on uncertain setups")
        if sim_wr < 45 and sim_wr > 0:
            improvements.append("This setup has a {:.0f}% win rate — consider avoiding or requiring higher confidence".format(sim_wr))
        if gate_stance.get("avg_confidence", 0) > 0 and gate_stance.get("avg_confidence", 0) < 50:
            improvements.append("Low gate confidence ({:.0f}%) — would benefit from tighter entry criteria".format(gate_stance["avg_confidence"]))
    else:
        # Win analysis — was it optimal?
        annotations = snap.get("annotations", [])
        exit_ann = next((a for a in annotations if a.get("type") == "exit"), None)
        if exit_ann:
            reasons = exit_ann.get("reasons", [])
            mfe_note = [r for r in reasons if "MFE" in r and "<50%" in r]
            if mfe_note:
                improvements.append("Only captured a fraction of MFE — trailing stop or scale-out could have captured more")
        if gate_stance.get("avg_confidence", 0) > 70:
            improvements.append("Gate confidence is high ({:.0f}%) — could size up on this setup for bigger wins".format(gate_stance["avg_confidence"]))
        if gate_stance.get("would_take_today") == "REDUCE":
            improvements.append("Despite this win, gate currently says REDUCE for this setup — may be a less reliable edge now")
        if gate_stance.get("would_take_today") == "SKIP":
            improvements.append("Gate now recommends SKIP for this setup — edge may have deteriorated since this trade")
        if sim_wr < 40 and sim_wr > 0:
            improvements.append("This setup's win rate is low ({:.0f}%) — this win may be an outlier rather than repeatable edge".format(sim_wr))
        if sim_wr >= 60:
            improvements.append("Strong {:.0f}% win rate on this setup — a reliable edge worth sizing into".format(sim_wr))

    if not improvements:
        if pnl > 0:
            improvements.append("Trade executed well within current model parameters")
        else:
            improvements.append("Model is still learning from this type of trade — more data needed")

    data["improvements"] = improvements
    return data


def _build_hindsight_prompt(snap: dict, data: dict) -> str:
    """Build the LLM prompt for hindsight analysis."""
    symbol = snap.get("symbol", "?")
    setup = snap.get("setup_type", "?")
    direction = snap.get("direction", "long").upper()
    pnl = snap.get("pnl", 0)
    outcome = data.get("trade_outcome", "?")
    close_reason = snap.get("close_reason", "?")

    similar = data.get("similar_trades", {})
    gate = data.get("current_gate_stance", {})
    loop = data.get("learning_loop", {})
    improvements = data.get("improvements", [])

    prompt = (
        f"You are an AI trading bot performing a hindsight self-review of a completed trade.\n"
        f"You must be honest and analytical. Use 'we' voice. Be specific about what you'd change.\n\n"
        f"TRADE REVIEWED:\n"
        f"  {symbol} {direction} ({setup}) — {outcome} ${pnl:+.2f}\n"
        f"  Entry: ${snap.get('entry_price', 0):.2f} → Exit: ${snap.get('exit_price', 0):.2f}\n"
        f"  Close reason: {close_reason}\n\n"
        f"SIMILAR TRADES PERFORMANCE ({similar.get('count', 0)} trades same setup/direction):\n"
        f"  Win rate: {similar.get('win_rate', 0):.1f}%\n"
        f"  Avg winner: ${similar.get('avg_win', 0):.2f} | Avg loser: ${similar.get('avg_loss', 0):.2f}\n"
        f"  Avg R:R: {similar.get('avg_risk_reward', 0):.2f}\n\n"
        f"CURRENT CONFIDENCE GATE STANCE (what we'd do TODAY for this setup):\n"
        f"  Recent decisions: {gate.get('recent_decisions', {})}\n"
        f"  Avg confidence: {gate.get('avg_confidence', 0):.0f}%\n"
        f"  Current regime: {gate.get('current_regime', '?')}\n"
        f"  Would take today: {gate.get('would_take_today', '?')}\n\n"
        f"LEARNING LOOP STATUS:\n"
        f"  Outcomes tracked: {loop.get('total_outcomes_tracked', 0)}\n"
        f"  Win rate from outcomes: {loop.get('win_rate_from_outcomes', 0):.1f}%\n"
        f"  Has model feedback: {loop.get('has_model_feedback', False)}\n\n"
        f"IDENTIFIED IMPROVEMENTS:\n"
    )
    for imp in improvements:
        prompt += f"  - {imp}\n"

    prompt += (
        "\nWrite a concise hindsight analysis (3-4 paragraphs) covering:\n"
        "1. Was this trade consistent with our current knowledge? Would we take it again today?\n"
        "2. What specific parameter changes (gate threshold, position size, stop placement, targets) would improve the outcome?\n"
        "3. What has the model learned from similar trades since this one?\n"
        "4. A 1-sentence 'verdict' at the end: what we'd do differently next time.\n"
        "Be specific, data-driven, and actionable. Don't be vague."
    )
    return prompt


def _top_values(items: list, top_n: int = 3) -> list:
    """Get top N most common values from a list."""
    from collections import Counter
    return [v for v, _ in Counter(items).most_common(top_n)]


def _call_llm_sync(prompt: str, context: str) -> str:
    """
    Call Ollama/GPT-OSS synchronously for annotation explanations.
    Falls back to structured response if LLM unavailable.
    """
    import httpx
    import os

    # Try Ollama HTTP proxy first
    try:
        from server import is_http_ollama_proxy_connected, call_ollama_via_http_proxy
        if is_http_ollama_proxy_connected():
            model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
            messages = [
                {"role": "system", "content": "You are an expert AI trading analyst. Be concise, insightful, and use 'we' voice."},
                {"role": "user", "content": prompt}
            ]
            response = call_ollama_via_http_proxy(messages, model=model, max_tokens=500)
            if response:
                return response
    except Exception as e:
        logger.debug(f"Ollama proxy not available: {e}")

    # Try direct Ollama URL
    ollama_url = os.environ.get("OLLAMA_URL", "")
    if ollama_url:
        try:
            model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
            resp = httpx.post(
                f"{ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are an expert AI trading analyst. Be concise and insightful. Use 'we' voice."},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False,
                    "options": {"num_predict": 500}
                },
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.debug(f"Direct Ollama call failed: {e}")

    # Try Emergent LLM key as fallback
    emergent_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if emergent_key:
        try:
            from emergentintegrations.llm.chat import chat, ChatMessage
            messages = [
                ChatMessage(role="system", content="You are an expert AI trading analyst. Be concise and insightful. Use 'we' voice."),
                ChatMessage(role="user", content=prompt)
            ]
            response = chat(
                api_key=emergent_key,
                model="claude-sonnet-4-20250514",
                messages=messages
            )
            if response and response.message:
                return response.message
        except Exception as e:
            logger.debug(f"Emergent LLM call failed: {e}")

    # Structured fallback — no LLM available
    return (
        "AI analysis is currently unavailable (Ollama/GPT-OSS not connected). "
        "The recorded decision data is shown in the annotation above. "
        "Connect your local Ollama instance for full AI-powered explanations."
    )
