"""
Document Processor Service
Ingests documents (PDFs, text) and uses AI to extract structured trading knowledge.
"""
import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from services.llm_service import get_llm_service
from services.knowledge_service import get_knowledge_service

logger = logging.getLogger(__name__)

# System prompt for knowledge extraction
EXTRACTION_SYSTEM_PROMPT = """You are an expert trading knowledge extractor. Your job is to read trading documents and extract structured, actionable knowledge.

For each piece of knowledge you extract, identify:
1. Type: strategy, pattern, indicator, rule, insight, checklist
2. Category: entry, exit, risk_management, position_sizing, market_condition, technical, fundamental, sentiment, premarket, intraday, swing, general
3. Key conditions/criteria that define when this applies
4. Confidence level based on how well-defined and actionable it is

Focus on extracting:
- Entry strategies with specific conditions
- Exit rules (profit targets, stop losses)
- Pattern recognition criteria
- Risk management rules
- Market condition filters
- Indicator setups and thresholds

Make knowledge ACTIONABLE - include specific numbers, conditions, and criteria whenever possible."""


class DocumentProcessor:
    """
    Processes documents and extracts trading knowledge using AI.
    """
    
    def __init__(self):
        self.llm = get_llm_service()
        self.knowledge = get_knowledge_service()
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text content from a PDF file"""
        try:
            import PyPDF2
            
            text = ""
            with open(pdf_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except ImportError:
            logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
            raise
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            raise
    
    def chunk_text(self, text: str, chunk_size: int = 4000, overlap: int = 500) -> List[str]:
        """Split text into chunks for processing"""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # Try to break at a paragraph or sentence
            if end < len(text):
                # Look for paragraph break
                para_break = text.rfind("\n\n", start, end)
                if para_break > start + chunk_size // 2:
                    end = para_break
                else:
                    # Look for sentence break
                    sentence_break = text.rfind(". ", start, end)
                    if sentence_break > start + chunk_size // 2:
                        end = sentence_break + 1
            
            chunks.append(text[start:end].strip())
            start = end - overlap if end < len(text) else end
        
        return [c for c in chunks if c]  # Remove empty chunks
    
    def extract_knowledge_from_chunk(self, chunk: str, source_name: str) -> List[Dict[str, Any]]:
        """Use AI to extract knowledge from a text chunk"""
        
        extraction_prompt = f"""Analyze this trading content and extract ALL actionable knowledge entries.

CONTENT:
{chunk}

Extract each distinct strategy, pattern, rule, or insight as a separate entry.
Return a JSON object with this structure:
{{
    "entries": [
        {{
            "title": "Short descriptive title",
            "content": "Full description with specific conditions and criteria",
            "type": "strategy|pattern|rule|insight|indicator|checklist",
            "category": "entry|exit|risk_management|position_sizing|market_condition|technical|fundamental|sentiment|premarket|intraday|swing|general",
            "tags": ["relevant", "tags"],
            "conditions": ["specific condition 1", "specific condition 2"],
            "confidence": 70-100 based on how specific and actionable
        }}
    ]
}}

Focus on ACTIONABLE knowledge with specific criteria. Skip general commentary.
If a strategy has multiple variations, create separate entries for each.
Include specific numbers (e.g., "RSI < 30", "Volume > 2x average") when mentioned."""

        try:
            result = self.llm.generate_json(extraction_prompt, EXTRACTION_SYSTEM_PROMPT, max_tokens=4000)
            entries = result.get("entries", [])
            
            # Add source to each entry
            for entry in entries:
                entry["source"] = f"document:{source_name}"
                entry["metadata"] = entry.get("metadata", {})
                entry["metadata"]["conditions"] = entry.pop("conditions", [])
                entry["metadata"]["extracted_at"] = datetime.now(timezone.utc).isoformat()
            
            return entries
        except Exception as e:
            logger.error(f"Error extracting knowledge from chunk: {e}")
            return []
    
    def process_document(self, content: str, source_name: str, content_type: str = "text") -> Dict[str, Any]:
        """
        Process a document and extract all knowledge.
        
        Args:
            content: Text content or file path (for PDFs)
            source_name: Name to identify this source
            content_type: "text" or "pdf"
        
        Returns:
            Summary of extracted knowledge
        """
        # Extract text if PDF
        if content_type == "pdf":
            text = self.extract_text_from_pdf(content)
        else:
            text = content
        
        if not text.strip():
            return {"error": "No content to process", "entries_created": 0}
        
        # Chunk the text
        chunks = self.chunk_text(text)
        logger.info(f"Processing document '{source_name}' in {len(chunks)} chunks")
        
        all_entries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            entries = self.extract_knowledge_from_chunk(chunk, source_name)
            all_entries.extend(entries)
        
        # Deduplicate by title similarity
        unique_entries = self._deduplicate_entries(all_entries)
        
        # Save to knowledge base
        saved_count = 0
        saved_entries = []
        for entry in unique_entries:
            try:
                result = self.knowledge.add(
                    title=entry.get("title", "Untitled"),
                    content=entry.get("content", ""),
                    type=entry.get("type", "insight"),
                    category=entry.get("category", "general"),
                    tags=entry.get("tags", []),
                    source=entry.get("source", "document"),
                    confidence=entry.get("confidence", 70),
                    metadata=entry.get("metadata", {})
                )
                saved_entries.append(result)
                saved_count += 1
            except Exception as e:
                logger.error(f"Error saving entry '{entry.get('title')}': {e}")
        
        return {
            "source": source_name,
            "chunks_processed": len(chunks),
            "entries_extracted": len(all_entries),
            "entries_after_dedup": len(unique_entries),
            "entries_saved": saved_count,
            "entries": saved_entries
        }
    
    def _deduplicate_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate entries based on title similarity"""
        unique = []
        seen_titles = set()
        
        for entry in entries:
            title = entry.get("title", "").lower().strip()
            # Simple dedup - exact title match
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique.append(entry)
        
        return unique
    
    def process_text_input(self, text: str, source_name: str = "user_input") -> Dict[str, Any]:
        """Process raw text input (copy-pasted content)"""
        return self.process_document(text, source_name, content_type="text")
    
    def process_pdf_file(self, file_path: str) -> Dict[str, Any]:
        """Process a PDF file"""
        source_name = os.path.basename(file_path)
        return self.process_document(file_path, source_name, content_type="pdf")
    
    def learn_from_insight(self, insight: str, context: str = None) -> Dict[str, Any]:
        """
        Quick learning from a single insight or observation.
        Use this for ad-hoc knowledge additions.
        """
        prompt = f"""Analyze this trading insight and structure it as knowledge:

INSIGHT: {insight}
{f"CONTEXT: {context}" if context else ""}

Return JSON:
{{
    "title": "Short title",
    "content": "Expanded, actionable description",
    "type": "insight|rule|pattern|strategy",
    "category": "appropriate category",
    "tags": ["relevant", "tags"],
    "confidence": 60-90
}}"""

        try:
            result = self.llm.generate_json(prompt, EXTRACTION_SYSTEM_PROMPT, max_tokens=1000)
            
            # Save to knowledge base
            saved = self.knowledge.add(
                title=result.get("title", insight[:50]),
                content=result.get("content", insight),
                type=result.get("type", "insight"),
                category=result.get("category", "general"),
                tags=result.get("tags", []),
                source="user_insight",
                confidence=result.get("confidence", 70)
            )
            
            return {"success": True, "entry": saved}
        except Exception as e:
            logger.error(f"Error learning from insight: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_document_processor: Optional[DocumentProcessor] = None

def get_document_processor() -> DocumentProcessor:
    """Get the singleton document processor instance"""
    global _document_processor
    if _document_processor is None:
        _document_processor = DocumentProcessor()
    return _document_processor
