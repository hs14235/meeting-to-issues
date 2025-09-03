import { createContext, useContext, useMemo, useState } from "react";

type Kind = "ok" | "err" | "info";
type ToastItem = { id: string; title: string; detail?: any; kind: Kind };

type Ctx = {
  push: (t: Omit<ToastItem, "id">) => void;
};

const ToastCtx = createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const api = useMemo<Ctx>(() => ({
    push: (t) => {
      const id = Math.random().toString(36).slice(2);
      setItems((s) => [...s, { ...t, id }]);
      // auto-dismiss
      setTimeout(() => {
        setItems((s) => s.filter((x) => x.id !== id));
      }, 4200);
    },
  }), []);

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div style={{
        position: "fixed", right: 16, bottom: 16,
        display: "grid", gap: 8, zIndex: 9999
      }}>
        {items.map((t) => (
          <div key={t.id} style={{
            background: t.kind === "err" ? "#391b1b"
                      : t.kind === "ok" ? "#14321f" : "#112233",
            color: "#e6f0ff",
            border: "1px solid #ffffff22",
            borderRadius: 10,
            padding: "10px 12px",
            maxWidth: 360,
            boxShadow: "0 6px 20px rgba(0,0,0,.35)",
          }}>
            <div style={{ fontWeight: 700 }}>{t.title}</div>
            {t.detail && (
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, opacity: .85, margin: 0 }}>
                {typeof t.detail === "string" ? t.detail : JSON.stringify(t.detail, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  const { push } = ctx;
  return {
    push,
    success: (title: string, detail?: any) => push({ kind: "ok", title, detail }),
    error:   (title: string, detail?: any) => push({ kind: "err", title, detail }),
    info:    (title: string, detail?: any) => push({ kind: "info", title, detail }),
  };
}
