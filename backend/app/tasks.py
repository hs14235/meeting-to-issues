from __future__ import annotations

from typing import List, Dict, Any, Optional
import os, re, json, httpx, logging


log = logging.getLogger(__name__)

# ====== Config ======
DEFAULT_LABEL = "meeting-action"
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "")
# Be generous on read timeout so local models have time to respond.
TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)

# ====== Small helpers ======
def _mk_task(body: str, who: Optional[str], due: Optional[str], i: int) -> Optional[Dict[str, Any]]:
    """Create a normalized task dict or None if body is empty."""
    body = (body or "").strip()
    if not body:
        return None
    title = body.rstrip(".")[:80]
    if not title:
        return None
    return {
        "title": title,
        "body": body if body.endswith(".") else body + ".",
        "labels": [DEFAULT_LABEL],
        "assignee_hint": who,
        "due_hint": due,
        "source_i": i,
        "confidence": 0.7,
    }

def extract_tasks_rules(context_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []

    # Patterns
    re_action     = re.compile(r'(?i)\b(Action|Todo|Task|AI)[:\-]\s*(.+)')  # "Action: do X"
    re_checkbox   = re.compile(r'(?i)^\s*[-*•]\s*\[(?: |x)\]\s*(.+)')       # "- [ ] do X"
    re_bullet     = re.compile(r'(?i)^\s*[-*•]\s*(.+)')                     # "- do X"
    re_person_to  = re.compile(r'(?i)^([A-Z][a-zA-Z]+)\s+(?:to|will|should)\s+(.+?)(?:\.|$)')
    re_owner_col  = re.compile(r'(?i)\b(?:owner|assignee)\s*[:\-]\s*([A-Z][\w-]+)\b')
    re_need       = re.compile(r'(?i)\b(?:need(?:s)? to|must|should|please|let\'?s|follow\s*up(?: on)?)\s+(.+?)(?:\.|$)')
    re_blocker    = re.compile(r'(?i)\bblocker[s]?:\s*(.+)')

    # very forgiving due date hint
    re_due = re.compile(
        r'(?i)\b(?:by|due|before)\s+(?:mon|tue|wed|thu|fri|sat|sun|tomorrow|eod|eow|'
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2})\b'
    )

    for ch in context_chunks:
        text, i = ch.get("text",""), ch.get("i", 0)

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue

            body = None
            who  = None

            m = re_action.search(line)
            if m:
                body = m.group(2).strip()
            else:
                m = re_checkbox.search(line)
                if m:
                    body = m.group(1).strip()
                else:
                    m = re_person_to.search(line)
                    if m:
                        who  = m.group(1)
                        body = m.group(2).strip()
                    else:
                        # catch generic "we/please/need to ..."
                        m = re_need.search(line)
                        if m:
                            body = m.group(1).strip()

            if not body:
                continue

            # owner hint from "owner: Bob"
            m_owner = re_owner_col.search(line)
            if m_owner and not who:
                who = m_owner.group(1)

            # due hint
            due = None
            m_due = re_due.search(line)
            if m_due:
                due = m_due.group(0)

            body_clean = body.rstrip(".")
            tasks.append({
                "title": body_clean[:80],
                "body":  body_clean + ".",
                "labels": ["meeting-action"],
                "assignee_hint": who,
                "due_hint": due,
                "source_i": i,
                "confidence": 0.6
            })

    return tasks


# ----------------------------
# Ollama
# ----------------------------
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")

TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=120.0, pool=5.0)

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # remove ```json ... ``` or ``` ... ```
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _json_lenient(text: str):
    # 1) direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) grab first {...} or [...]
    m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
    if m:
        candidate = m.group(1)
        # 3) fix common trailing comma errors
        candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except Exception:
            pass
    logging.warning("LLM JSON salvage failed")
    return None

def _parse_tasks_json(text: str) -> List[Dict[str, Any]]:
    text = _strip_code_fences(text)
    obj = _json_lenient(text)
    if obj is None:
        return []

    tasks = obj if isinstance(obj, list) else obj.get("tasks", [])
    out: List[Dict[str, Any]] = []
    for t in tasks or []:
        labels = t.get("labels") or ["meeting-action"]
        if isinstance(labels, str):
            labels = [labels]
        try:
            si = int(t.get("source_i", 0))
        except Exception:
            si = 0
        try:
            conf = float(t.get("confidence", 0.7))
        except Exception:
            conf = 0.7

        out.append({
            "title": (t.get("title", "") or "").strip(),
            "body": (t.get("body", "") or "").strip(),
            "labels": labels,
            "assignee_hint": t.get("assignee_hint"),
            "due_hint": t.get("due_hint"),
            "source_i": si,
            "confidence": max(0.0, min(1.0, conf)),
        })
    return [t for t in out if t["title"] or t["body"]]
async def extract_tasks_ollama(context_texts: List[str]) -> List[Dict[str, Any]]:
    if not OLLAMA_MODEL:
        return []

    system = (
        "You extract actionable tasks from meeting snippets.\n"
        "Return ONLY JSON (either an array, or {\"tasks\": [...]}) with objects:\n"
        "title, body, labels (string[]), assignee_hint, due_hint, source_i, confidence."
    )
    user = "Snippets:\n" + "\n---\n".join(f"[{i}] {t}" for i, t in enumerate(context_texts))

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user",   "content": user}],
        "options": {"temperature": 0.2, "num_predict": 320, "num_ctx": 4096},
        "format": "json",     
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            text = (r.json().get("message") or {}).get("content", "")
    except Exception as e:
        log.warning("Ollama request failed: %s", e)
        return []

    try:
        return _parse_tasks_json(text)
    except Exception as e:
        log.warning("Ollama parse failed: %s", e)
        return []

__all__ = ["extract_tasks_rules", "extract_tasks_ollama"]
