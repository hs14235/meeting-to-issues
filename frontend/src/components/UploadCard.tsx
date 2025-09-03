import { useRef, useState } from "react";
import { useToast } from "./Toast";

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8000";

export default function UploadCard() {
  const [meetingId, setMeetingId] = useState("mtg-005");
  const [title, setTitle]         = useState("Sample meeting");
  const [msg, setMsg]             = useState<string>("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [drag, setDrag] = useState(false);
  const { success, error } = useToast();

  async function doUpload(file?: File) {
    const f = file ?? fileRef.current?.files?.[0];
    if (!f) { error("Choose a file first"); return; }

    const form = new FormData();
    form.append("file", f);
    form.append("meeting_id", meetingId);
    form.append("title", title || "");

    setMsg("Uploading…");
    const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      setMsg("Upload failed");
      error("Upload failed", data);
      return;
    }

    setMsg("Indexed ✓");
    success("Upload & index complete", { meetingId, title });
    // Broadcast for TaskExtractor's recent-meetings datalist
    window.dispatchEvent(new CustomEvent("mtg-added", { detail: { id: meetingId } }));
  }

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) await doUpload(f);
  };

  return (
    <div className="card">
      <div className="row" style={{ alignItems: "stretch" }}>
        <input className="txt" value={meetingId}
               onChange={e=>setMeetingId(e.target.value)} placeholder="meeting id"/>
        <input className="txt" value={title}
               onChange={e=>setTitle(e.target.value)} placeholder="title"/>

        {/* drag & drop zone + file picker */}
        <div
          onDragOver={(e)=>{e.preventDefault(); setDrag(true);}}
          onDragLeave={()=>setDrag(false)}
          onDrop={onDrop}
          style={{
            border: "1px dashed #5b6b89",
            borderRadius: 10,
            padding: 10,
            minWidth: 220,
            textAlign: "center",
            background: drag ? "#0f172a" : "transparent"
          }}
          title="Drag a transcript here"
        >
          Drag transcript here or{" "}
          <label style={{ textDecoration: "underline", cursor: "pointer" }}>
            browse
            <input type="file" accept=".txt,.md,.rtf,.pdf,.doc,.docx"
                   style={{ display:"none" }}
                   ref={fileRef}
                   onChange={(e)=>{ const f=e.target.files?.[0]; if (f) doUpload(f); }}/>
          </label>
        </div>

        <button className="btn" onClick={() => doUpload()}>Upload & Index</button>
      </div>
      <div className="small">{msg}</div>
    </div>
  );
}
