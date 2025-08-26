import os
from .base import VectorStore
from .memory_store import MemoryStore
from .faiss_store import FaissStore

def get_store(dim: int, backend: str, index_path: str, meta_path: str) -> VectorStore:
    if backend.lower() == "faiss":
        try:
            return FaissStore(dim, index_path, meta_path)
        except Exception:
            # fall back gracefully
            return MemoryStore()
    return MemoryStore()
