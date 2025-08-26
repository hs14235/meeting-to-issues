# backend/app/tasks.py
from typing import List, Dict, Any
import os, re, json
import httpx

# ----------------------------
# Free regex/heuristic extractor
# ----------------------------
def extract_tasks_rules(context_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    re_action   = re.compile(r'(?i)\b(Action|Todo|Task)[:\-]\s*(.+)')
    re_checkbox = re.compile(r'(?i)^\s*[-*]\s*\[(?: |x)\]\s*(.+)')
    re_person   = re.compile(r'(?i)^([A-Z][a-zA-Z]+)\s+to\s+(.+?)(?:\.|$)')

    for ch in context_chunks:
        text, i = ch["text"], ch["i"]
        for raw in text.splitlines():
            line = raw.strip()
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
                    m = re_person.search(line)
                    if m:
                        who  = m.group(1)
                        body = m.group(2).strip()

            if not body:
                continue

            due = None
            m_due = re.search(r'(?i)\bby\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\w+\s+\d{1,2})', line)
            if m_due:
                due = m_due.group(0)

            tasks.append({
                "title": body[:80].rstrip("."),
                "body":  body if body.endswith(".") else body + ".",
                "labels": ["meeting-action"],
                "assignee_hint": who,
                "due_hint": due,
                "source_i": i,
                "confidence": 0.6
            })
    return tasks

# ----------------------------
# Free local LLM via Ollama
# ----------------------------
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")

async def extract_tasks_ollama(context_texts: List[str]) -> List[Dict[str, Any]]:
    """Ask a local Ollama model to extract tasks as structured JSON."""
    if not OLLAMA_MODEL:
        return []

    system = "You are a precise project manager. Extract concrete, actionable tasks."
    user = (
          "Read the meeting snippets and extract ONLY concrete, actionable tasks people must do.\n"
  "Return a JSON object with key 'tasks' whose value is an array of objects with keys: "
  "title, body, labels (string[]), assignee_hint, due_hint, source_i, confidence (0..1).\n"
  "- One action per task. Do NOT combine or summarize multiple actions into one item.\n"
  "- Exclude agenda/status like 'Kickoff' unless it contains an explicit action.\n"
  "- Prefer imperative phrasing in 'title'.\n"
  "- If no assignee or due is clear, leave them null.\n"
  "- Keep titles ≤ 80 chars. Default label: 'meeting-action'.\n\n"
  "Snippets:\n" + "\n---\n".join(f"[{i}] {t}" for i, t in enumerate(context_texts))
)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user}
        ],
        "options": {"temperature": 0.2, "num_predict": 400},
        "stream": False
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            # try to salvage the first JSON object in the text
            m = re.search(r'\{[\s\S]*\}', content)
            obj = json.loads(m.group(0)) if m else {"tasks": []}
        tasks = obj.get("tasks", [])
        # ensure minimum shape
        out: List[Dict[str, Any]] = []
        for t in tasks:
            out.append({
                "title": t.get("title", ""),
                "body":  t.get("body", ""),
                "labels": t.get("labels") or ["meeting-action"],
                "assignee_hint": t.get("assignee_hint"),
                "due_hint":      t.get("due_hint"),
                "source_i":      t.get("source_i", 0),
                "confidence":    t.get("confidence", 0.7),
            })
        return out

__all__ = ["extract_tasks_rules", "extract_tasks_ollama"]
