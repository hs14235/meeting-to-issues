import { useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";

const PRESET_QUERIES = [
  "action items",
  "decisions",
  "follow-ups blockers",
  "risks",
  "bugs & regressions",
] as const;
type Preset = typeof PRESET_QUERIES[number];

const repoRegex = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

function readList(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch { return []; }
}
function writeList(key: string, arr: string[]) {
  localStorage.setItem(key, JSON.stringify([...new Set(arr)].slice(0, 10)));
}

type Task = {
  title?: string;
  body?: string;
  labels?: string[];
  assignee_hint?: string;
  due_hint?: string;
  source_i?: number;
  confidence?: number;
};

type StreamEvt =
  | { stage: "retrieving" }
  | { stage: "ollama"; progress?: number; chunks?: number }
  | { stage: "parsing" }
  | { stage: "rules_fallback" }
  | { stage: "done"; mode: "ollama" | "rules"; tasks: Task[] }
  | { stage: "error"; message: string }
  | Record<string, unknown>;

type CreatedItem = { number?: number; url?: string; title: string; status: string };
type ApiError = { detail?: Record<string, any> } | Record<string, any>;

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8000";

export default function TaskExtractor() {
  const { success, error } = useToast();

  // 🔧 Restore query state
  const [q, setQ] = useState("action items");

  const [meetingId, setMeetingId] = useState("mtg-001");
  const [repo, setRepo] = useState("owner/repo");
  const [selected, setSelected] = useState<Preset[]>(["action items"]);
  const [k, setK] = useState(5);

  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string>("idle");
  const [mode, setMode] = useState<"ollama" | "rules" | "">("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [preview, setPreview] = useState<any[] | null>(null);
  const [created, setCreated] = useState<CreatedItem[] | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // recent lists
  const [recentMeetings, setRecentMeetings] = useState<string[]>(() => readList("recentMeetings"));
  const [recentRepos, setRecentRepos]       = useState<string[]>(() => readList("recentRepos"));

  const repoOk = repoRegex.test((repo || "").trim()) && repo.trim().toLowerCase() !== "owner/repo";

  useEffect(() => writeList("recentRepos", recentRepos), [recentRepos]);

  useEffect(() => {
    const onAdded = (e: any) => {
      const id = e?.detail?.id || e?.detail;
      if (!id) return;
      setRecentMeetings(prev => {
        const next = [id, ...prev];
        writeList("recentMeetings", next);
        return [...new Set(next)].slice(0, 10);
      });
    };
    window.addEventListener("mtg-added", onAdded);
    return () => window.removeEventListener("mtg-added", onAdded);
  }, []);

  // ── Extract (single query) ───────────────────────────────────────────────
  async function start() {
    setProgress(5);
    setStage("starting");
    setMode("");
    setTasks([]);
    setPreview(null);
    setCreated(null);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const res = await fetch(`${API_BASE}/tasks/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meeting_id: meetingId, q, k }), // <- uses q
      signal: ctrl.signal
    });

    if (!res.ok || !res.body) {
      let payload: any = {};
      try { payload = await res.json(); } catch {}
      const d = (payload as ApiError).detail ?? payload ?? {};
      error("Failed to start extraction", d);
      setStage("error");
      return;
    }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += dec.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        if (!frame.startsWith("data:")) continue;
        try {
          const evt = JSON.parse(frame.replace(/^data:\s*/, "")) as StreamEvt;
          if ("stage" in evt) setStage(String((evt as any).stage));
          if ((evt as any).progress) setProgress(Number((evt as any).progress));
          if ((evt as any).stage === "ollama" && typeof (evt as any).progress === "number") {
            setProgress((evt as any).progress);
          } else if ((evt as any).stage === "rules_fallback") {
            setProgress(96);
          } else if ((evt as any).stage === "done" && "tasks" in evt) {
            setProgress(100);
            setMode((evt as any).mode);
            setTasks((evt as any).tasks || []);
          } else if ((evt as any).stage === "error") {
            setStage("error");
          }
        } catch {}
      }
    }
  }

  function stop() {
    abortRef.current?.abort();
    setStage("aborted");
  }

  // ── Optional helpers for future "Run selected" (multi-query) ─────────────
  function togglePreset(p: Preset) {
    setSelected(s => s.includes(p) ? s.filter(x => x !== p) : [...s, p]);
    setQ(p); // keep the current single q in the text box
  }
  function normTitle(s: string=""){ return s.toLowerCase().replace(/\s+/g," ").trim(); }
  async function extractOnce(query: string): Promise<Task[]> {
    const res = await fetch(`${API_BASE}/tasks/stream`,{
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ meeting_id: meetingId, q: query, k })
    });
    if (!res.ok || !res.body) return [];
    const dec = new TextDecoder();
    const reader = res.body.getReader();
    let buf = ""; let out: Task[] = [];
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n"); buf = frames.pop() || "";
      for (const f of frames) {
        if (!f.startsWith("data:")) continue;
        const evt = JSON.parse(f.replace(/^data:\s*/, ""));
        if (evt.stage === "done" && Array.isArray(evt.tasks)) out = evt.tasks as Task[];
      }
    }
    return out;
  }
  async function runSelectedPresets() {
    setTasks([]); setPreview(null); setCreated(null);
    setStage("retrieving"); setProgress(10);
    const all: Task[] = [];
    for (const p of selected) {
      const t = await extractOnce(p);
      all.push(...t);
    }
    const seen = new Set<string>();
    const deduped = all.filter(t => {
      const key = normTitle(t.title || "");
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    setTasks(deduped);
    setProgress(100); setStage("done");
  }

  // ── Preview / Create ─────────────────────────────────────────────────────
  async function doPreview() {
    setPreview(null);
    const payload = { repo, meeting_id: meetingId, tasks };
    const res = await fetch(`${API_BASE}/issues/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let data: any = {};
    try { data = await res.json(); } catch {}

    if (!res.ok) {
      const d = (data as ApiError).detail ?? data ?? {};
      error("Preview failed", d);
      return;
    }
    setPreview(Array.isArray(data.would_create) ? data.would_create : []);
  }

  async function doCreate() {
    if (!repoOk) {
      error("Please enter a real GitHub repo like yourname/yourrepo");
      return;
    }
    const payload = { repo, meeting_id: meetingId, tasks };
    const res = await fetch(`${API_BASE}/issues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let data: any = {};
    try { data = await res.json(); } catch {}

    if (!res.ok) {
      const d = (data as ApiError).detail ?? data ?? {};
      error("Failed to create issues", d);
      return;
    }
    const createdArr: CreatedItem[] = Array.isArray(data.created) ? data.created : [];
    setCreated(createdArr);

    const nCreated = createdArr.filter(x => x.status === "created").length;
    const nDupes   = createdArr.filter(x => x.status === "skipped-duplicate").length;
    const nSkipped = createdArr.length - nCreated;
    success(`Created ${nCreated}, skipped ${nSkipped}${nDupes ? ` (${nDupes} duplicates)` : ""}`);
  }

  // ── UI ───────────────────────────────────────────────────────────────────
  return (
    <div>
      {/* Top controls */}
      <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {/* Meeting ID with recent list */}
        <datalist id="recent-meetings">
          {recentMeetings.map(m => <option key={m} value={m} />)}
        </datalist>
        <input
          list="recent-meetings"
          className="txt"
          value={meetingId}
          onChange={e=>setMeetingId(e.target.value)}
          placeholder="meeting id"
        />

        {/* Repo with recent list + validity */}
        <datalist id="recent-repos">
          {recentRepos.map(r => <option key={r} value={r} />)}
        </datalist>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            list="recent-repos"
            className="txt"
            value={repo}
            onChange={e => {
              const v = e.target.value;
              setRepo(v);
              if (repoRegex.test(v)) {
                setRecentRepos(prev => [v, ...prev].slice(0, 10));
              }
            }}
            placeholder="repo (owner/name)"
            title="owner/name"
          />
          <span style={{ fontSize: 12, color: repoOk ? "#34d399" : "#f87171" }}>
            {repoOk ? "✓ looks valid" : "Github username/Repository"}
          </span>
        </div>

        {/* K slider */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="range" min={1} max={10} value={k}
                 onChange={e => setK(Number(e.target.value))} />
          <span className="small">
            K = [ {k} ] How many chunks we feed to the model as context. More chunks = broader recall; heavier on CPU.
          </span>
        </div>

        {/* Extract / Stop */}
        {["starting","retrieving","extracting","parsing"].includes(stage)
          ? <button className="btn" onClick={stop}>Stop</button>
          : <button className="btn" onClick={start}>Extract</button>}
      </div>

      {/* Query presets + custom input (single-select chips) */}
      <div style={{ display:"flex", gap:8, flexWrap:"wrap", alignItems:"center", marginTop:8 }}>
        {PRESET_QUERIES.map(p => (
          <button
            key={p}
            type="button"
            className="btn"
            onClick={() => { setQ(p); setSelected([p]); }}
            style={{
              borderRadius: 999,
              borderColor: selected.includes(p) ? "#5b83d1" : undefined,
              boxShadow: selected.includes(p) ? "0 0 0 2px #20365c inset" : undefined
            }}
            title={`Use "${p}"`}
          >
            {p}
          </button>
        ))}
        {/* Optional: a button to run all selected presets */}
        {/* <button className="btn" onClick={runSelectedPresets}>Run selected</button> */}

        {/* Free text query still supported */}
        <input
          className="txt"
          value={q}
          onChange={e=>setQ(e.target.value)}
          placeholder="custom query"
        />
      </div>

      {/* Progress */}
      <div className="bar"><div className="barFill" style={{ width: `${progress}%` }} /></div>
      <div className="small">stage: {stage} ({progress}%) {mode && `• mode: ${mode}`}</div>

      {/* Tasks */}
      <div className="tasks">
        {tasks.length === 0 && <div className="muted">No tasks yet.</div>}
        {tasks.map((t, i) => (
          <div key={i} className="task">
            <div className="tTitle">{t.title || "(no title)"}</div>
            {t.body && <pre className="tBody">{t.body}</pre>}
            <div className="tMeta">
              labels: {(t.labels || []).join(", ") || "—"} • source_i: {t.source_i ?? "—"} • conf: {t.confidence ?? "—"}
            </div>
          </div>
        ))}
      </div>

      {/* Preview / Create */}
      <div className="row">
        <button className="btn" onClick={doPreview} disabled={!tasks.length}>Preview Issues</button>
        <button className="btn" onClick={doCreate}  disabled={!tasks.length}>Create Issues</button>
      </div>

      {/* Preview list */}
      {preview && (
        <div className="preview">
          <h3>Preview</h3>
          {preview.map((p, idx) => (
            <div key={idx} className="task">
              <div className="tTitle">{p.title}</div>
              <pre className="tBody">{p.body}</pre>
              <div className="tMeta">labels: {(p.labels || []).join(", ")}</div>
            </div>
          ))}
        </div>
      )}

      {/* Created results */}
      {created && (
        <div className="preview">
          <h3>Result</h3>
          {created.map((r, i) => (
            <div key={i} className="task">
              <div className="tTitle">
                {r.title} — <span className="small">{r.status}</span>
              </div>
              {r.url && <a href={r.url} target="_blank" rel="noreferrer">{r.url}</a>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
