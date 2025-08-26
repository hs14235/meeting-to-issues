from fastapi import FastAPI, UploadFile, Form, Body, HTTPException
import httpx, traceback
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List
import hashlib, os

from .config import API_TITLE, ALLOWED_ORIGINS, RAG_STORE, EMBED_MODEL, FAISS_INDEX, FAISS_META
from .chunking import to_chunks
from .embeddings import embed_texts
from .vectorstore.factory import get_store
from .storage import save_meeting, load_chunks
from .tasks import extract_tasks_ollama, extract_tasks_rules
from .github import ensure_labels, create_issue

DIM = 384  # MiniLM-L6-v2 output size
store = get_store(DIM, RAG_STORE, FAISS_INDEX, FAISS_META)

app = FastAPI(title=API_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _id(text: str, meta: Dict[str, Any]):
    return hashlib.sha256((text + str(meta)).encode("utf-8")).hexdigest()[:16]

@app.get("/")
def root():
    return {"ok": True}

@app.post("/upload")
async def upload(file: UploadFile, meeting_id: str = Form(...), title: str = Form("")):
    raw = (await file.read()).decode("utf-8", errors="ignore")
    chunks = to_chunks(raw)
    save_meeting(meeting_id, title, raw, chunks)

    metas = [{"meeting_id": meeting_id, "title": title, "i": i} for i, _ in enumerate(chunks)]
    ids = [_id(chunks[i], metas[i]) for i in range(len(chunks))]
    vecs = embed_texts(chunks, EMBED_MODEL)
    store.upsert(ids, vecs, metas)
    store.persist()
    return {"ok": True, "chunks_indexed": len(chunks)}

@app.get("/search")
def search(meeting_id: str, q: str, k: int = 5):
    qvec = embed_texts([q], EMBED_MODEL)[0]
    res = store.query(qvec, k=k, filters={"meeting_id": meeting_id})
    return {"results": [{"id": rid, "score": score, "meta": meta} for rid, score, meta in res]}

@app.post("/tasks")
async def tasks(payload: Dict[str, Any] = Body(...)):
    """
    Body: {"meeting_id": "...", "q": "action items", "k": 5}
    """
    meeting_id = payload["meeting_id"]
    q = payload.get("q", "action items from this meeting")
    k = int(payload.get("k", 5))

    # 1) retrieve top-k snippets
    qvec = embed_texts([q], EMBED_MODEL)[0]
    hits = store.query(qvec, k=k, filters={"meeting_id": meeting_id})
    idxs = [h[2].get("i") for h in hits]

    # 2) load texts (fallback to first k chunks if retrieval is empty)
    all_chunks: List[Dict[str, Any]] = load_chunks(meeting_id)
    if not idxs:
        idxs = [c["i"] for c in all_chunks[:k]]
    context = [c for c in all_chunks if c["i"] in idxs]
    context_texts = [c["text"] for c in context]

    # 3) try Ollama first (free local LLM)
    tasks_llm = await extract_tasks_ollama(context_texts)

    if tasks_llm:
       

        #  normalization 
        # Map/validate source_i so it always points to a *global* chunk index
        valid = set(idxs)
        def norm_src(x):
            try:
                v = int(x)
            except Exception:
                return idxs[0] if idxs else 0
            # If model already returned a global chunk index and it's valid
            if v in valid:
                return v
            # If model returned a *position in the retrieved list* (0..len(idxs)-1), map it
            if 0 <= v < len(idxs):
                return idxs[v]
            # Fallback to the first retrieved chunk
            return idxs[0] if idxs else 0

        # ---------- Return mapping (normalize each task object) ----------
        normalized = []
        for t in tasks_llm:
            normalized.append({
                "title": t.get("title", ""),
                "body": t.get("body", ""),
                "labels": t.get("labels") or ["meeting-action"],
                "assignee_hint": t.get("assignee_hint"),
                "due_hint": t.get("due_hint"),
                "source_i": norm_src(t.get("source_i")),
                "confidence": t.get("confidence", 0.7),
            })
        return {"tasks": normalized, "mode": "ollama"}

    # 4) fallback: rules
    rules = extract_tasks_rules(context)
    return {"tasks": rules, "mode": "rules"}


@app.post("/issues")
async def create_issues(payload: Dict[str, Any] = Body(...)):
    try:
        """
        Body:
        {
          "repo": "hs14235/meeting-to-issues",
          "meeting_id": "mtg-002",     # optional, adds source snippet
          "tasks": [
            { "title": "...", "body": "...", "labels": ["meeting-action"], "assignee_hint": "Hamza", "source_i": 0 }
        ],
        "assignee_map": { "Hamza": "hs14235" }  # optional
       }
       """
        repo: str = payload["repo"]
        meeting_id: str | None = payload.get("meeting_id")
        tasks = payload["tasks"]
        assignee_map: Dict[str, str] = payload.get("assignee_map") or {}

        # optional: include meeting snippets in issue body
        snippet_by_i: Dict[int, str] = {}
        if meeting_id:
            for c in load_chunks(meeting_id):
                snippet_by_i[c["i"]] = c["text"]

        # ensure labels exist
        all_labels = sorted({lab for t in tasks for lab in (t.get("labels") or [])})
        await ensure_labels(repo, all_labels)

        created = []
        for t in tasks:
            title = t.get("title") or "(no title)"
            body  = t.get("body") or ""
            si    = t.get("source_i")
            if meeting_id is not None and si is not None:
                snippet = snippet_by_i.get(si, "")
                if snippet:
                    snippet = snippet if len(snippet) < 400 else (snippet[:400] + "…")
                    body += f"\n\n_Source: meeting `{meeting_id}`, chunk #{si}_\n```\n{snippet}\n```"

            # map hint -> GitHub username (only collaborators can be assigned)
            hint = t.get("assignee_hint")
            gh_user = None
            if isinstance(hint, str):
                gh_user = assignee_map.get(hint) or assignee_map.get(hint.lower())

            labels = t.get("labels") or ["meeting-action"]
            issue = await create_issue(repo=repo, title=title, body=body, labels=labels, assignee=gh_user)
            created.append({"number": issue["number"], "url": issue["html_url"], "title": issue["title"]})
        return {"created": created}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail={
            "where": "github",
            "status": e.response.status_code,
            "text": e.response.text
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "where": "server",
            "error": str(e),
            "trace_tail": traceback.format_exc().splitlines()[-4:],
        })