from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple

class VectorStore(ABC):
    @abstractmethod
    def upsert(self, ids: List[str], embeddings: List[List[float]], metas: List[Dict[str, Any]]): ...
    @abstractmethod
    def query(self, embedding: List[float], k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str,float,Dict[str,Any]]]: ...
    @abstractmethod
    def persist(self): ...
