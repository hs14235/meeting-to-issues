# backend/app/github.py
from typing import List, Optional, Dict, Any
import os, httpx

BASE = "https://api.github.com"

def _headers():
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

async def ensure_labels(repo: str, labels: List[str]) -> None:
    if not labels:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{BASE}/repos/{repo}/labels", headers=_headers(), params={"per_page": 100})
        r.raise_for_status()
        existing = {l["name"].lower() for l in r.json()}
        to_create = [l for l in labels if l and l.lower() not in existing]
        for name in to_create:
            payload = {"name": name, "color": "ededed", "description": "auto-created by meeting-to-issues"}
            rr = await client.post(f"{BASE}/repos/{repo}/labels", headers=_headers(), json=payload)
            if rr.status_code not in (200, 201, 422):
                rr.raise_for_status()

async def create_issue(repo: str, title: str, body: str,
                       labels: Optional[List[str]] = None,
                       assignee: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title": title, "body": body}
    if labels:   payload["labels"] = labels
    if assignee: payload["assignees"] = [assignee]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE}/repos/{repo}/issues", headers=_headers(), json=payload)
        if r.status_code == 422 and assignee:
            payload.pop("assignees", None)  # retry without assignee
            r = await client.post(f"{BASE}/repos/{repo}/issues", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()
