from typing import List, Dict, Any, Optional, Tuple

from .base import VectorStore

class MemoryStore(VectorStore):
    """
    In-memory fallback: perfect for getting started.
    """
    def __init__(self):
        self._ids: List[str] = []
        self._vecs: List[List[float]] = []
        self._meta: List[Dict[str, Any]] = []

    def upsert(self, ids, embeddings, metas):
        self._ids.extend(ids)
        self._vecs.extend(embeddings)
        self._meta.extend(metas)

    def query(self, embedding, k=5, filters=None):
        if not self._ids:
            return []
        # cosine since vectors are normalized: score = dot(q, v)
        scores = [sum(a*b for a, b in zip(embedding, vec)) for vec in self._vecs]
        order = sorted(range(len(self._ids)), key=lambda i: -scores[i])
        out = []
        for i in order:
            m = self._meta[i]
            if filters and any(m.get(k) != v for k, v in (filters or {}).items()):
                continue
            out.append((self._ids[i], float(scores[i]), m))
            if len(out) >= k:
                break
        return out

    def persist(self):
        # no-op for MVP
        pass
