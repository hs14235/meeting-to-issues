import os

API_TITLE = "Meeting → Issues API"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# vector store choice: 'faiss' (if installed) or 'memory'
RAG_STORE = os.getenv("RAG_STORE", "faiss")

# sentence-transformers model (free & solid)
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# FAISS file locations (only used if RAG_STORE=faiss and faiss is installed)
FAISS_INDEX = os.getenv("FAISS_INDEX", "../data/faiss.index")
FAISS_META  = os.getenv("FAISS_META",  "../data/faiss_meta.json")
