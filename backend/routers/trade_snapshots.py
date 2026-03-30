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
