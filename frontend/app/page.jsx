"use client";
import { useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import {
  Upload, Link, Key, Zap, Copy, Download, RefreshCw,
  CheckCircle, AlertCircle, Loader2, ChevronRight, Eye, Code2, X
} from "lucide-react";

const SandpackPreview = dynamic(() => import("../components/SandpackPreview"), { ssr: false });

const STEP_ICONS = {
  start: Zap,
  figma_fetch: Link,
  figma_image: Eye,
  analyze: Eye,
  generate: Code2,
  validate: CheckCircle,
  fix: RefreshCw,
  fidelity_review: Eye,
  fidelity_fix: RefreshCw,
  asset_fix: Upload,
  done: CheckCircle,
};

const STEP_COLORS = {
  start: "#6366f1",
  figma_fetch: "#8b5cf6",
  figma_image: "#06b6d4",
  analyze: "#06b6d4",
  generate: "#6366f1",
  validate: "#22c55e",
  fix: "#f59e0b",
  fidelity_review: "#06b6d4",
  fidelity_fix: "#f59e0b",
  asset_fix: "#22c55e",
  done: "#22c55e",
  error: "#ef4444",
};

const getBackendBaseUrl = () => {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }

  return "http://localhost:8000";
};

export default function Home() {
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaToken, setFigmaToken] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [logs, setLogs] = useState([]);
  const [generatedCode, setGeneratedCode] = useState("");
  const [activeTab, setActiveTab] = useState("preview");
  const [status, setStatus] = useState("idle"); // idle | running | done | error
  const [copied, setCopied] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef();
  const logsEndRef = useRef();

  const addLog = (entry) => {
    setLogs((prev) => [...prev, { ...entry, ts: Date.now() }]);
    setTimeout(() => logsEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  const handleImageDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer?.files?.[0] || e.target?.files?.[0];
    if (!file) return;
    setImageFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => setImagePreview(ev.target.result);
    reader.readAsDataURL(file);
  }, []);

  const removeImage = () => {
    setImageFile(null);
    setImagePreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const canRun = (figmaUrl.trim() || imageFile) && status !== "running";

  const handleGenerate = async () => {
    if (!canRun) return;
    setLogs([]);
    setGeneratedCode("");
    setStatus("running");

    const formData = new FormData();
    if (figmaUrl.trim()) formData.append("figma_url", figmaUrl.trim());
    if (figmaToken.trim()) formData.append("figma_token", figmaToken.trim());
    if (imageFile) formData.append("image", imageFile);

    try {
      const res = await fetch(`${getBackendBaseUrl()}/generate`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok || !res.body) {
        throw new Error(`Backend request failed (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "log") {
              addLog(event);
            } else if (event.type === "result") {
              setGeneratedCode(event.code);
              setStatus("done");
            } else if (event.type === "error") {
              addLog({ type: "error", step: "error", message: event.message });
              setStatus("error");
            }
          } catch {}
        }
      }
    } catch (err) {
      addLog({ type: "error", step: "error", message: `Connection error: ${err.message}` });
      setStatus("error");
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(generatedCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([generatedCode], { type: "text/javascript" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "GeneratedComponent.jsx";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadZip = async () => {
    // Dynamically load JSZip from CDN
    if (!window.JSZip) {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    const JSZip = window.JSZip;
    const zip = new JSZip();

    // package.json
    zip.file("package.json", JSON.stringify({
      name: "generated-react-app",
      version: "0.1.0",
      private: true,
      scripts: { dev: "vite", build: "vite build", preview: "vite preview" },
      dependencies: { react: "^18.2.0", "react-dom": "^18.2.0" },
      devDependencies: {
        "@vitejs/plugin-react": "^4.2.1",
        vite: "^5.2.0",
        tailwindcss: "^3.4.1",
        autoprefixer: "^10.4.19",
        postcss: "^8.4.38",
      },
    }, null, 2));

    // vite.config.js
    zip.file("vite.config.js", `import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()] })
`);

    // tailwind.config.js
    zip.file("tailwind.config.js", `/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
}
`);

    // postcss.config.js
    zip.file("postcss.config.js", `export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
`);

    // index.html
    zip.file("index.html", `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Generated App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
`);

    // src/main.jsx
    zip.file("src/main.jsx", `import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import GeneratedComponent from './GeneratedComponent'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GeneratedComponent />
  </React.StrictMode>,
)
`);

    // src/index.css
    zip.file("src/index.css", `@tailwind base;\n@tailwind components;\n@tailwind utilities;\n`);

    // The actual generated component
    zip.file("src/GeneratedComponent.jsx", generatedCode);

    // README
    zip.file("README.md", `# Generated React App

This project was generated by the Figma → React Agent.

## Getting started

\`\`\`bash
npm install
npm run dev
\`\`\`

Open http://localhost:5173

The main component is in \`src/GeneratedComponent.jsx\`.
You can import and use it anywhere in your app.
`);

    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "generated-react-app.zip";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <header className="border-b px-6 py-4 flex items-center gap-3" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "var(--accent)" }}>
          <Zap size={16} className="text-white" />
        </div>
        <div>
          <h1 className="font-semibold text-sm" style={{ color: "var(--text)" }}>Figma → React Agent</h1>
          <p className="text-xs" style={{ color: "var(--muted)" }}>Powered by Agno + GPT-4o</p>
        </div>
      </header>

      {/* Main 3-panel layout */}
      <div className="flex flex-1 overflow-hidden" style={{ height: "calc(100vh - 57px)" }}>

        {/* LEFT PANEL — Input */}
        <div className="flex flex-col gap-4 p-4 overflow-y-auto scrollbar-thin"
          style={{ width: 300, minWidth: 280, background: "var(--surface)", borderRight: "1px solid var(--border)" }}>

          <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--muted)" }}>Input</p>

          {/* Figma URL */}
          <div>
            <label className="text-xs mb-1.5 block" style={{ color: "var(--muted)" }}>
              <Link size={11} className="inline mr-1" />Figma URL <span style={{ color: "var(--muted)" }}>(optional)</span>
            </label>
            <input
              type="text"
              placeholder="https://figma.com/design/..."
              value={figmaUrl}
              onChange={(e) => setFigmaUrl(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg outline-none focus:ring-1"
              style={{
                background: "var(--surface2)", border: "1px solid var(--border)",
                color: "var(--text)", focusRingColor: "var(--accent)"
              }}
            />
          </div>

          {/* Figma Token */}
          <div>
            <label className="text-xs mb-1.5 block" style={{ color: "var(--muted)" }}>
              <Key size={11} className="inline mr-1" />Figma API Token <span style={{ color: "var(--muted)" }}>(optional)</span>
            </label>
            <input
              type="password"
              placeholder="figd_..."
              value={figmaToken}
              onChange={(e) => setFigmaToken(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg outline-none"
              style={{ background: "var(--surface2)", border: "1px solid var(--border)", color: "var(--text)" }}
            />
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
              Get from Figma → Settings → Personal access tokens
            </p>
          </div>

          {/* Image upload */}
          <div>
            <label className="text-xs mb-1.5 block" style={{ color: "var(--muted)" }}>
              <Upload size={11} className="inline mr-1" />Screenshot <span style={{ color: "var(--muted)" }}>(optional)</span>
            </label>
            {imagePreview ? (
              <div className="relative rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
                <img src={imagePreview} alt="preview" className="w-full object-cover" style={{ maxHeight: 160 }} />
                <button onClick={removeImage}
                  className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full flex items-center justify-center"
                  style={{ background: "rgba(0,0,0,0.7)" }}>
                  <X size={12} className="text-white" />
                </button>
              </div>
            ) : (
              <div
                className="rounded-lg flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors"
                style={{
                  border: `2px dashed ${dragging ? "var(--accent)" : "var(--border)"}`,
                  background: dragging ? "rgba(99,102,241,0.05)" : "var(--surface2)",
                  padding: "24px 16px"
                }}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleImageDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={20} style={{ color: "var(--muted)" }} />
                <p className="text-xs text-center" style={{ color: "var(--muted)" }}>
                  Drop screenshot here<br />or click to browse
                </p>
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleImageDrop} />
              </div>
            )}
          </div>

          <p className="text-xs p-2 rounded-lg" style={{ background: "rgba(99,102,241,0.1)", color: "var(--muted)", border: "1px solid rgba(99,102,241,0.2)" }}>
            You can provide a URL, a screenshot, or both. The more context, the better the output.
          </p>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={!canRun}
            className="w-full py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all"
            style={{
              background: canRun ? "var(--accent)" : "var(--surface2)",
              color: canRun ? "white" : "var(--muted)",
              cursor: canRun ? "pointer" : "not-allowed",
            }}
          >
            {status === "running" ? (
              <><Loader2 size={15} className="animate-spin" /> Generating...</>
            ) : (
              <><Zap size={15} /> Generate React Code</>
            )}
          </button>

          {/* Status badge */}
          {status !== "idle" && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs"
              style={{
                background: status === "done" ? "rgba(34,197,94,0.1)" : status === "error" ? "rgba(239,68,68,0.1)" : "rgba(99,102,241,0.1)",
                color: status === "done" ? "var(--success)" : status === "error" ? "var(--error)" : "var(--accent)",
                border: `1px solid ${status === "done" ? "rgba(34,197,94,0.2)" : status === "error" ? "rgba(239,68,68,0.2)" : "rgba(99,102,241,0.2)"}`
              }}>
              {status === "done" ? <CheckCircle size={12} /> : status === "error" ? <AlertCircle size={12} /> : <Loader2 size={12} className="animate-spin" />}
              {status === "done" ? "Code generated successfully" : status === "error" ? "Generation failed" : "Running agent..."}
            </div>
          )}
        </div>

        {/* MIDDLE PANEL — Agent Log */}
        <div className="flex flex-col overflow-hidden"
          style={{ width: 300, minWidth: 260, borderRight: "1px solid var(--border)", background: "var(--bg)" }}>
          <div className="px-4 py-3 border-b flex items-center gap-2" style={{ borderColor: "var(--border)" }}>
            <div className="w-2 h-2 rounded-full" style={{ background: status === "running" ? "var(--accent)" : status === "done" ? "var(--success)" : "var(--muted)" }} />
            <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--muted)" }}>Agent activity</p>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-2">
            {logs.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-3" style={{ color: "var(--muted)" }}>
                <Zap size={28} style={{ opacity: 0.3 }} />
                <p className="text-xs text-center">Agent logs will appear here<br />once you click Generate</p>
              </div>
            )}
            {logs.map((log, i) => {
              const Icon = STEP_ICONS[log.step] || ChevronRight;
              const color = log.type === "error" ? STEP_COLORS.error : (STEP_COLORS[log.step] || "var(--muted)");
              return (
                <div key={i} className="flex gap-2.5 items-start">
                  <div className="mt-0.5 w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0"
                    style={{ background: `${color}20` }}>
                    <Icon size={11} style={{ color }} />
                  </div>
                  <div>
                    <p className="text-xs leading-relaxed" style={{ color: log.type === "error" ? "var(--error)" : "var(--text)" }}>
                      {log.message}
                    </p>
                  </div>
                </div>
              );
            })}
            <div ref={logsEndRef} />
          </div>
        </div>

        {/* RIGHT PANEL — Code + Preview */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Tabs + actions bar */}
          <div className="flex items-center gap-1 px-4 py-3 border-b flex-wrap gap-y-2"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
            {["preview", "code"].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className="px-3 py-1.5 rounded-md text-xs font-medium transition-all"
                style={{
                  background: activeTab === tab ? "var(--accent)" : "transparent",
                  color: activeTab === tab ? "white" : "var(--muted)"
                }}
              >
                {tab === "preview"
                  ? <><Eye size={11} className="inline mr-1" />Live Preview</>
                  : <><Code2 size={11} className="inline mr-1" />Code</>}
              </button>
            ))}

            {generatedCode && (
              <div className="ml-auto flex items-center gap-2 flex-wrap">
                <button onClick={handleCopy}
                  className="px-3 py-1.5 rounded-md text-xs flex items-center gap-1.5"
                  style={{ background: "var(--surface2)", color: copied ? "var(--success)" : "var(--muted)", border: "1px solid var(--border)" }}>
                  <Copy size={11} />{copied ? "Copied!" : "Copy code"}
                </button>
                <button onClick={handleDownload}
                  className="px-3 py-1.5 rounded-md text-xs flex items-center gap-1.5"
                  style={{ background: "var(--surface2)", color: "var(--muted)", border: "1px solid var(--border)" }}>
                  <Download size={11} />.jsx only
                </button>
                <button onClick={handleDownloadZip}
                  className="px-3 py-1.5 rounded-md text-xs flex items-center gap-1.5 font-medium"
                  style={{ background: "var(--accent)", color: "white", border: "none" }}>
                  <Download size={11} />Download full project .zip
                </button>
              </div>
            )}
          </div>

          {/* Info banner — shown when preview is active and code exists */}
          {generatedCode && activeTab === "preview" && (
            <div className="flex items-start gap-2.5 px-4 py-2.5 text-xs border-b"
              style={{
                background: "rgba(99,102,241,0.08)",
                borderColor: "rgba(99,102,241,0.2)",
                color: "var(--muted)"
              }}>
              <Eye size={12} style={{ color: "var(--accent)", marginTop: 1, flexShrink: 0 }} />
              <span>
                <span style={{ color: "var(--text)", fontWeight: 500 }}>Live preview</span>
                {" "}— the component renders here in-browser via Sandpack (no setup needed).
                To use it in your own project, click{" "}
                <span style={{ color: "var(--accent)", fontWeight: 500 }}>Download full project .zip</span>
                {" "}→ unzip → <code style={{ fontFamily: "monospace", background: "rgba(255,255,255,0.08)", padding: "0 4px", borderRadius: 3 }}>npm install && npm run dev</code>.
              </span>
            </div>
          )}

          {/* Content */}
          <div className="flex-1 overflow-hidden">
            {!generatedCode ? (
              <div className="h-full flex flex-col items-center justify-center gap-3" style={{ color: "var(--muted)" }}>
                <Code2 size={40} style={{ opacity: 0.2 }} />
                <p className="text-sm">Generated component will appear here</p>
                <p className="text-xs text-center px-8" style={{ opacity: 0.6 }}>
                  The preview tab shows it live in the browser.<br />
                  The code tab shows the raw JSX you can copy or download.
                </p>
              </div>
            ) : activeTab === "preview" ? (
              <SandpackPreview code={generatedCode} />
            ) : (
              <pre className="h-full overflow-auto p-4 text-xs leading-relaxed scrollbar-thin"
                style={{ background: "var(--bg)", color: "#a9b1d6", fontFamily: "monospace" }}>
                {generatedCode}
              </pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
