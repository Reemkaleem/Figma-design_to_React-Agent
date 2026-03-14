"use client";
import { Sandpack } from "@codesandbox/sandpack-react";
import { atomDark } from "@codesandbox/sandpack-themes";

function stripMarkdownFences(input) {
  const trimmed = (input || "").trim();
  if (!trimmed) return "";
  return trimmed
    .replace(/^```(?:jsx?|tsx?|react)?\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
}

function ensureDefaultExport(source) {
  if (/\bexport\s+default\b/.test(source)) {
    return source;
  }

  const componentMatch = source.match(
    /\b(?:function|const|let|var)\s+([A-Z][A-Za-z0-9_]*)\s*(?:\(|=)/
  );

  if (componentMatch?.[1]) {
    return `${source}\n\nexport default ${componentMatch[1]};`;
  }

  return `import React from "react";

export default function GeneratedComponent() {
  return (
    <div style={{ padding: 16, fontFamily: "sans-serif", color: "#111827" }}>
      <h3 style={{ margin: 0, fontSize: 16 }}>Preview unavailable</h3>
      <p style={{ marginTop: 8, fontSize: 13 }}>
        The generated output did not include a default component export.
      </p>
    </div>
  );
}
`;
}

function normalizeGeneratedCode(rawCode) {
  let code = stripMarkdownFences(rawCode);

  if (!code) {
    return `import React from "react";

export default function GeneratedComponent() {
  return <div style={{ padding: 16 }}>No code generated yet.</div>;
}
`;
  }

  // Drop stylesheet imports that don't exist inside the sandbox.
  code = code.replace(/^\s*import\s+["'][^"']+\.css["'];?\s*$/gm, "");

  // If model prefixes explanation text, keep only from the first likely code line.
  const lines = code.split("\n");
  const firstCodeLine = lines.findIndex((line) =>
    /^\s*(import|export|function|const|let|var|class)\b/.test(line)
  );
  if (firstCodeLine > 0) {
    code = lines.slice(firstCodeLine).join("\n").trim();
  }

  return ensureDefaultExport(code);
}

export default function SandpackPreview({ code }) {
  const generatedComponentCode = normalizeGeneratedCode(code);
  const appCode = `import React from "react";
import GeneratedComponent from "./GeneratedComponent";

export default function App() {
  return <GeneratedComponent />;
}
`;

  return (
    <div style={{ height: "100%", minHeight: 0, overflow: "hidden" }}>
      <Sandpack
        theme={atomDark}
        template="react"
        style={{ height: "100%" }}
        options={{
          showPreview: true,
          showConsole: true,
          showNavigator: false,
          showTabs: false,
          externalResources: [
            "https://cdn.tailwindcss.com",
          ],
          layout: "preview",
        }}
        files={{
          "/App.js": {
            code: appCode,
            active: true,
          },
          "/GeneratedComponent.jsx": {
            code: generatedComponentCode,
          },
        }}
        customSetup={{
          dependencies: {
            react: "^18",
            "react-dom": "^18",
            "lucide-react": "^0.383.0",
          },
        }}
      />
    </div>
  );
}
