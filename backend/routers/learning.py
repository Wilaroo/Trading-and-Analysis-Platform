"""
AI Learning API Router
Endpoints for the AI knowledge ingestion and learning system.
"""
import os
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from services.llm_service import get_llm_service
from services.document_processor import get_document_processor
from services.knowledge_service import get_knowledge_service

router = APIRouter(prefix="/api/learn", tags=["AI Learning"])


class TextInput(BaseModel):
    """Schema for text-based learning input"""
    content: str = Field(..., min_length=10, description="Text content to learn from")
    source_name: str = Field(default="user_input", description="Name for this content source")


class InsightInput(BaseModel):
    """Schema for quick insight learning"""
    insight: str = Field(..., min_length=10, description="The insight or observation")
    context: Optional[str] = Field(None, description="Additional context")


class QueryInput(BaseModel):
    """Schema for knowledge queries"""
    query: str = Field(..., min_length=3, description="What to search for")
    types: Optional[List[str]] = Field(None, description="Filter by types")
    limit: int = Field(default=10, ge=1, le=50)


@router.get("/status")
async def get_learning_status():
    """
    Get the status of the AI learning system.
    Shows which LLM provider is active and knowledge base stats.
    """
    llm = get_llm_service()
    knowledge = get_knowledge_service()
    
    return {
        "llm": llm.get_status(),
        "knowledge_base": knowledge.get_stats(),
        "ready": llm.is_available
    }


@router.post("/text")
async def learn_from_text(input: TextInput):
    """
    Learn from text content.
    
    Paste trading strategies, rules, or any educational content.
    The AI will extract and structure the knowledge automatically.
    
    Example: Paste content from a trading book, blog post, or your own notes.
    """
    llm = get_llm_service()
    if not llm.is_available:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider available. Set OPENAI_API_KEY or EMERGENT_LLM_KEY."
        )
    
    processor = get_document_processor()
    result = processor.process_text_input(input.content, input.source_name)
    
    return {
        "success": True,
        "message": f"Extracted {result['entries_saved']} knowledge entries",
        "details": result
    }


@router.post("/pdf")
async def learn_from_pdf(
    file: UploadFile = File(..., description="PDF file to learn from")
):
    """
    Learn from a PDF document.
    
    Upload trading PDFs (strategy guides, educational material, etc.)
    The AI will read, extract, and structure all knowledge automatically.
    """
    llm = get_llm_service()
    if not llm.is_available:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider available. Set OPENAI_API_KEY or EMERGENT_LLM_KEY."
        )
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Save uploaded file temporarily
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        processor = get_document_processor()
        result = processor.process_pdf_file(tmp_path)
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        return {
            "success": True,
            "message": f"Processed '{file.filename}' - extracted {result['entries_saved']} knowledge entries",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


@router.post("/insight")
async def learn_insight(input: InsightInput):
    """
    Quick learning from a single insight or observation.
    
    Use this for quick additions like:
    - "VWAP rejections in the first 30 minutes are more reliable"
    - "Avoid trading small caps on FOMC days"
    - "Look for volume confirmation on breakouts above 2x average"
    
    The AI will structure and categorize it automatically.
    """
    llm = get_llm_service()
    if not llm.is_available:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider available. Set OPENAI_API_KEY or EMERGENT_LLM_KEY."
        )
    
    processor = get_document_processor()
    result = processor.learn_from_insight(input.insight, input.context)
    
    if result.get("success"):
        return {
            "success": True,
            "message": "Insight learned and stored",
            "entry": result["entry"]
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))


@router.post("/query")
async def query_knowledge(input: QueryInput):
    """
    Query the knowledge base with AI-enhanced search.
    
    Ask questions like:
    - "What strategies work for gap ups?"
    - "How should I manage risk on momentum plays?"
    - "What are the best entry conditions for breakouts?"
    """
    knowledge = get_knowledge_service()
    
    # First, do a direct search
    results = knowledge.search(
        query=input.query,
        limit=input.limit
    )
    
    # If LLM is available, generate a synthesized answer
    llm = get_llm_service()
    synthesized = None
    
    if llm.is_available and results:
        try:
            context = "\n\n".join([
                f"**{r['title']}** ({r['type']})\n{r['content']}"
                for r in results[:5]
            ])
            
            prompt = f"""Based on this trading knowledge, answer the question.

KNOWLEDGE BASE:
{context}

QUESTION: {input.query}

Provide a concise, actionable answer based on the knowledge above. If the knowledge doesn't fully answer the question, say so."""

            synthesized = llm.generate(prompt, max_tokens=500, temperature=0.5)
        except Exception as e:
            logger.error(f"Error generating synthesized answer: {e}")
    
    return {
        "query": input.query,
        "results": results,
        "count": len(results),
        "synthesized_answer": synthesized
    }


@router.get("/relevant/{symbol}")
async def get_relevant_knowledge(symbol: str, limit: int = 5):
    """
    Get knowledge relevant to a specific stock or situation.
    
    This can be used by the scanner/intelligence systems to pull
    relevant strategies and rules for a given symbol.
    """
    knowledge = get_knowledge_service()
    
    # Search for relevant entries
    results = knowledge.search(query=symbol, limit=limit)
    
    # Also get general strategies and rules
    strategies = knowledge.get_strategies(limit=10)
    rules = knowledge.get_rules(limit=10)
    
    return {
        "symbol": symbol,
        "direct_matches": results,
        "applicable_strategies": strategies[:5],
        "applicable_rules": rules[:5]
    }


@router.post("/bulk")
async def bulk_learn(entries: List[Dict[str, Any]]):
    """
    Bulk import knowledge entries.
    
    Use this to import pre-structured knowledge.
    Each entry should have: title, content, type, category, tags
    """
    knowledge = get_knowledge_service()
    
    saved = 0
    errors = []
    
    for entry in entries:
        try:
            knowledge.add(
                title=entry.get("title", "Untitled"),
                content=entry.get("content", ""),
                type=entry.get("type", "note"),
                category=entry.get("category", "general"),
                tags=entry.get("tags", []),
                source=entry.get("source", "bulk_import"),
                confidence=entry.get("confidence", 70),
                metadata=entry.get("metadata", {})
            )
            saved += 1
        except Exception as e:
            errors.append({"entry": entry.get("title"), "error": str(e)})
    
    return {
        "success": True,
        "saved": saved,
        "errors": errors if errors else None
    }


@router.post("/analyze/{symbol}")
async def analyze_with_knowledge(symbol: str, stock_data: Dict[str, Any] = None):
    """
    Analyze a stock using the knowledge base.
    
    Returns applicable strategies, trade bias, and AI recommendations
    based on learned trading knowledge.
    
    Args:
        symbol: Stock ticker symbol
        stock_data: Optional dict with rvol, gap_percent, vwap_position, rsi_14, etc.
    """
    from services.knowledge_integration import get_knowledge_integration
    
    ki = get_knowledge_integration()
    stock_data = stock_data or {}
    stock_data["symbol"] = symbol
    
    result = ki.get_knowledge_summary_for_symbol(symbol, stock_data)
    
    return {
        "success": True,
        "analysis": result
    }


@router.post("/enhance-opportunities")
async def enhance_opportunities(data: Dict[str, Any]):
    """
    Enhance a list of trading opportunities with knowledge base insights.
    
    Args:
        data: {
            "opportunities": List of opportunity dicts with symbol, price, change_percent, etc.
            "market_regime": "bullish" | "bearish" | "neutral"
        }
    """
    from services.knowledge_integration import get_knowledge_integration
    
    ki = get_knowledge_integration()
    
    opportunities = data.get("opportunities", [])
    market_regime = data.get("market_regime", "neutral")
    
    enhanced = await ki.enhance_market_intelligence(opportunities, market_regime, include_news=True)
    
    return {
        "success": True,
        "enhanced_opportunities": enhanced["opportunities"],
        "strategy_insights": enhanced["top_strategy_insights"],
        "knowledge_stats": enhanced["knowledge_base_stats"],
        "market_news": enhanced.get("market_news")
    }


@router.get("/ai-recommendation/{symbol}")
async def get_ai_recommendation(symbol: str, rvol: float = 1.0, gap_percent: float = 0, 
                                 vwap_position: str = "UNKNOWN", rsi: float = 50):
    """
    Get an AI-powered trade recommendation for a symbol.
    
    Uses the knowledge base and LLM to generate a specific trade recommendation
    with entry, stop, and target prices.
    """
    from services.knowledge_integration import get_knowledge_integration
    
    ki = get_knowledge_integration()
    
    stock_data = {
        "symbol": symbol,
        "rvol": rvol,
        "gap_percent": gap_percent,
        "vwap_position": vwap_position,
        "rsi_14": rsi,
        "current_price": 0  # Would need to be provided or fetched
    }
    
    recommendation = ki.generate_ai_trade_recommendation(stock_data)
    
    if recommendation:
        return {
            "success": True,
            "recommendation": recommendation
        }
    else:
        return {
            "success": False,
            "message": "Could not generate AI recommendation. LLM may be unavailable or no applicable strategies found."
        }


# Import logger
import logging
logger = logging.getLogger(__name__)
