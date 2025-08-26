try:
    import faiss  # type: ignore
except Exception:
    faiss = None

import os, json, numpy as np
from typing import List, Dict, Any, Optional, Tuple
from .base import VectorStore

class FaissStore(VectorStore):
    def __init__(self, dim: int, index_path: str, meta_path: str):
        self.dim, self.index_path, self.meta_path = dim, index_path, meta_path
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self.ids: List[str] = []
        self.id_to_meta: Dict[str, Any] = {}
        if faiss and os.path.exists(index_path) and os.path.exists(meta_path):
            self.index = faiss.read_index(index_path)
            meta = json.load(open(meta_path, "r", encoding="utf-8"))
            self.ids = meta["ids"]
            self.id_to_meta = meta["id_to_meta"]
        else:
            self.index = faiss.IndexFlatIP(dim) if faiss else None  # inner product

    def _norm(self, X):
        X = np.asarray(X, dtype="float32")
        n = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
        return (X / n).astype("float32")

    def upsert(self, ids, embeddings, metas):
        if not faiss or self.index is None:
            raise RuntimeError("FAISS not available")
        X = self._norm(embeddings)
        self.index.add(X)
        self.ids.extend(ids)
        for i, _id in enumerate(ids):
            self.id_to_meta[_id] = metas[i]

    def query(self, embedding, k=5, filters=None):
        if not faiss or self.index is None or not self.ids:
            return []
        q = self._norm([embedding])
        scores, idxs = self.index.search(q, min(k, len(self.ids)))
        out = []
        for j, s in zip(idxs[0], scores[0]):
            _id = self.ids[j]
            m = self.id_to_meta.get(_id, {})
            if filters and any(m.get(k) != v for k, v in (filters or {}).items()):
                continue
            out.append((_id, float(s), m))
        return out

    def persist(self):
        if not faiss or self.index is None:
            return
        faiss.write_index(self.index, self.index_path)
        json.dump({"ids": self.ids, "id_to_meta": self.id_to_meta}, open(self.meta_path, "w", encoding="utf-8"))
