from pathlib import Path
import os, json
from typing import List, Dict, Any

DATA_ROOT = Path(os.getenv("DATA_DIR", "../data")).resolve()

def _meeting_dir(meeting_id: str) -> Path:
    d = (DATA_ROOT / "meetings" / meeting_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_meeting(meeting_id: str, title: str, raw_text: str, chunks: List[str]) -> None:
    d = _meeting_dir(meeting_id)
    (d / "raw.txt").write_text(raw_text, encoding="utf-8")
    payload = {"meeting_id": meeting_id, "title": title,
               "chunks": [{"i": i, "text": ch} for i, ch in enumerate(chunks)]}
    (d / "chunks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def load_chunks(meeting_id: str) -> List[Dict[str, Any]]:
    f = (DATA_ROOT / "meetings" / meeting_id / "chunks.json")
    if not f.exists(): return []
    obj = json.loads(f.read_text(encoding="utf-8"))
    return obj.get("chunks", [])
