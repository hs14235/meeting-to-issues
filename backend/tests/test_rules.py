from app.tasks import extract_tasks_rules

def test_rules_finds_actions():
    context = [
        {"i": 0, "text": "Action: Hamza to wire FastAPI endpoints by Friday."},
        {"i": 1, "text": "Status: We discussed timelines."},
    ]
    tasks = extract_tasks_rules(context)
    titles = [t["title"].lower() for t in tasks]
    assert any("wire fastapi" in t for t in titles)
