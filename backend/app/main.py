from fastapi import FastAPI, UploadFile, Form, Body, HTTPException, Request
from httpx import ReadTimeout
from fastapi.middleware.cors import CORSMiddleware
import json, asyncio, httpx, logging, traceback
from typing import Dict, Any, List
import hashlib, re

from .config import API_TITLE, ALLOWED_ORIGINS, RAG_STORE, EMBED_MODEL, FAISS_INDEX, FAISS_META
from .chunking import to_chunks
from .embeddings import embed_texts
from .vectorstore.factory import get_store
from .storage import save_meeting, load_chunks
from .tasks import OLLAMA_URL, OLLAMA_MODEL, TIMEOUT, _parse_tasks_json, extract_tasks_rules, extract_tasks_ollama
from fastapi.responses import StreamingResponse
from .github import ensure_labels, create_issue, find_issue_by_fp, task_fingerprint
from typing import Optional

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def _sse(d: dict) -> str:
    return f"data: {json.dumps(d)}\n\n"

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
    
    try:
        tasks_llm = await extract_tasks_ollama(context_texts)
    except Exception as e:
        logging.warning("extract_tasks_ollama raised: %s", e)
        tasks_llm = []

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
        repo: str = payload["repo"]
        log.info(f"/issues repo={repo}")  
        # friendly validation (owner/repo)
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
            raise HTTPException(status_code=400, detail={
                "where": "client",
                "error": f'Invalid repo "{repo}". Use "hs14235/meeting-to-issues"'
            })
        meeting_id: Optional[str] = payload.get("meeting_id")
        tasks = payload["tasks"]
        assignee_map: Dict[str, str] = payload.get("assignee_map") or {}

        # Optional: cache meeting chunks for source snippets
        snippet_by_i: Dict[int, str] = {}
        if meeting_id:
            for c in load_chunks(meeting_id):
                snippet_by_i[c["i"]] = c["text"]

        # Ensure labels exist
        all_labels = sorted({lab for t in tasks for lab in (t.get("labels") or [])})
        if all_labels:
            await ensure_labels(repo, all_labels)

        created = []
        for t in tasks:
            title = (t.get("title") or "").strip()
            if not title:
                created.append({"title": "(empty)", "status": "skipped-empty-title"})
                continue
            body  = (t.get("body")  or "").strip()
            si    = t.get("source_i")  # <-- FIX: define si
            fp    = task_fingerprint(title, body)

            # hidden fingerprint marker for idempotency
            body += f"\n\n<!-- mtg:{meeting_id} fp:{fp} -->"

            # add short source snippet
            if meeting_id is not None and si is not None:
                snippet = snippet_by_i.get(si, "")
                if snippet:
                    if len(snippet) > 400:
                        snippet = snippet[:400] + "…"
                    body += f"\n\n_Source: meeting `{meeting_id}`, chunk #{si}_\n```\n{snippet}\n```"

            # skip duplicate if already open
            existing = await find_issue_by_fp(repo, fp)
            if existing:
                created.append({
                    "number": existing["number"],
                    "url": existing["html_url"],
                    "title": title,
                    "status": "skipped-duplicate",
                })
                continue

            # optional assignee mapping
            gh_user = None
            hint = t.get("assignee_hint")
            if isinstance(hint, str):
                gh_user = assignee_map.get(hint) or assignee_map.get(hint.lower())

            labels = t.get("labels") or ["meeting-action"]
            if isinstance(labels, str):
                labels = [labels]

            issue = await create_issue(
                repo,
                title,
                body,
                labels=labels,
            )
            created.append({
                "number": issue["number"],
                "url": issue["html_url"],
                "title": title,
                "status": "created",
            })

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
    
@app.post("/issues/preview")
async def issues_preview(payload: Dict[str, Any] = Body(...)):
    """
    Body: { "repo": "hs14235/meeting-to-issues", "meeting_id": "...", "tasks": [ ... ] }
    Returns: what we'd send to GitHub, but does NOT create anything.
    """
    repo: str = payload["repo"]
    meeting_id: str | None = payload.get("meeting_id")
    tasks = payload["tasks"]

    snippet_by_i = {}
    if meeting_id:
        for c in load_chunks(meeting_id):
            snippet_by_i[c["i"]] = c["text"]

    preview = []
    for t in tasks:
        body = t.get("body","")
        si = t.get("source_i")
        if meeting_id is not None and si is not None:
            snip = snippet_by_i.get(si, "")
            if snip:
                snip = snip if len(snip) < 400 else (snip[:400] + "…")
                body += f"\n\n_Source: meeting `{meeting_id}`, chunk #{si}_\n```\n{snip}\n```"
        preview.append({
            "repo": repo,
            "title": t.get("title","(no title)"),
            "body": body,
            "labels": t.get("labels") or ["meeting-action"]
        })
    return {"would_create": preview}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/tasks/stream")
async def tasks_stream(request: Request, payload: Dict[str, Any] = Body(...)):
    """
    Body: {"meeting_id": "...", "q": "action items", "k": 5}
    Streams stages: retrieving -> ollama (many) -> parsing -> rules_fallback? -> done
    """
    async def gen():
        try:
            # 1) retrieve context (reuse logic from /tasks)
            meeting_id = payload["meeting_id"]
            q = payload.get("q", "action items from this meeting")
            k = int(payload.get("k", 5))

            await asyncio.sleep(0)  # let loop breathe
            yield _sse({"stage": "retrieving"})

            qvec = embed_texts([q], EMBED_MODEL)[0]
            hits = store.query(qvec, k=k, filters={"meeting_id": meeting_id})
            idxs = [h[2].get("i") for h in hits]

            all_chunks = load_chunks(meeting_id)
            if not idxs:
                idxs = [c["i"] for c in all_chunks[:k]]
            context = [c for c in all_chunks if c["i"] in idxs]
            context_texts = [c["text"] for c in context]

            # 2) stream ollama if configured
            if not OLLAMA_MODEL:
                yield _sse({"stage": "parsing", "note": "OLLAMA_MODEL not set; using rules"})
                tasks = extract_tasks_rules(context)
                yield _sse({"stage": "done", "mode": "rules", "tasks": tasks})
                return

            system = (
                    "You extract actionable tasks from snippets and return ONLY valid minified JSON. "
                    "NO prose, NO markdown. Shape:\n"
                    '{"tasks":[{"title":"","body":"","labels":["meeting-action"],'
                    '"assignee_hint":null,"due_hint":null,"source_i":0,"confidence":0.7}]}\n'
                    "Rules: (1) JSON only. (2) No backticks. (3) Use integers for source_i. "
                    "(4) labels is an array of strings. (5) confidence in [0,1]. "
                    "(6) Return at most 15 tasks."
            )
            user = "Snippets:\n" + "\n---\n".join(f"[{i}] {t}" for i, t in enumerate(context_texts))
            req = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": "json",
                "stream": True,
                "options": {"temperature": 0.2, "num_predict": 1000, "num_ctx": 4096},
                
            }

            chunk_text = ""
            chunks = 0
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=req) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if await request.is_disconnected():
                                return
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            if obj.get("done"):
                                break
                            msg = (obj.get("message") or {}).get("content")
                            if msg:
                                chunk_text += msg
                                chunks += 1
                                # pseudo-progress: cap at 95 until parse
                                pct = min(95, 10 + chunks * 3)
                                yield _sse({"stage": "ollama", "progress": pct, "chunks": chunks})
            except Exception as e:
                log.warning("ollama stream failed: %s", e)
                chunk_text = ""  # force fallback

            # 3) parse or fallback to rules
            if chunk_text:
                yield _sse({"stage": "parsing"})
                tasks = _parse_tasks_json(chunk_text)
                if tasks:
                    yield _sse({"stage": "done", "mode": "ollama", "tasks": tasks})
                    return

            yield _sse({"stage": "rules_fallback"})
            tasks = extract_tasks_rules(context)
            yield _sse({"stage": "done", "mode": "rules", "tasks": tasks})

        except Exception as e:
            yield _sse({"stage": "error", "message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )