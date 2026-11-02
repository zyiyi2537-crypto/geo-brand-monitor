"""Re-export the shared EngineAdapter base for browser engines."""
from api_engine.base import EngineAdapter, EngineResult, Citation, extract_urls_from_text, extract_citations_from_json

__all__ = ["EngineAdapter", "EngineResult", "Citation", "extract_urls_from_text", "extract_citations_from_json"]
