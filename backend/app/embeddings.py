from sentence_transformers import SentenceTransformer

_model = None

def get_embedder(name: str):
    global _model
    if _model is None:
        _model = SentenceTransformer(name)
    return _model

def embed_texts(texts, name: str):
    m = get_embedder(name)
    # normalize=True ⇒ inner product ≈ cosine similarity
    return m.encode(texts, normalize_embeddings=True).tolist()
