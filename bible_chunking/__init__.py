"""
Bible Chunking Module for Hierarchical RAG

This module provides tools for parsing Bible markdown files
and converting them to hierarchical JSONL format suitable for
RAG applications with vector databases and knowledge graphs.
"""

from .config import BOOK_CONFIG, TOKEN_CONFIG
from .models import Book, Chapter, Pericope, Chunk, Verse

__version__ = "1.0.0"
__all__ = [
    "BOOK_CONFIG",
    "TOKEN_CONFIG",
    "Book",
    "Chapter",
    "Pericope",
    "Chunk",
    "Verse",
]
