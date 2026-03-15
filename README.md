# Figma → React Agent

Convert Figma designs into production-ready React + Tailwind CSS components using an Agno-powered AI agent.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Next.js Frontend                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  Input   │  │ Agent Logs   │  │ Preview + Code    │  │
│  │  Panel   │  │   Panel      │  │     Panel         │  │
│  │          │  │              │  │  (Sandpack live)  │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          │ SSE Stream
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Backend                          │
│                                                          │
│  FigmaToReactAgent (Agno)                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │ 1. fetch_figma_data  → Figma REST API            │    │
│  │ 2. fetch_figma_image → Render node as PNG        │    │
│  │ 3. build_messages    → Vision + JSON context     │    │
│  │ 4. generate          → GPT-4o (OpenAI compat.)   │    │
│  │ 5. validate          → Static JSX checks         │    │
│  │ 6. fix (if needed)   → Self-healing loop x3      │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Add your API key

```bash
cd backend
cp .env.example .env
# Edit .env and add your key:
# GITHUB_COPILOT_API_KEY=your_key_here
```

**Getting a GitHub Copilot API key:**
- Go to https://github.com/settings/tokens
- Create a token with `copilot` scope
- Or use any OpenAI-compatible API key (OpenAI, Azure OpenAI, etc.)

### 2. Start everything

```bash
chmod +x start.sh
./start.sh
```

Or manually:

**Backend:**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend (new terminal):**
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## Using the App

### Input options (use one or both)

| Option | Quality | When to use |
|--------|---------|-------------|
| Figma URL only | Good | Quick generation from design structure |
| Screenshot only | Good | When you don't have Figma API access |
| Both URL + Screenshot | Best | Maximum context for the agent |

### Figma API Token
- Required only if providing a Figma URL
- Get it: Figma → Account Settings → Personal access tokens
- The token is used client-side only, never stored

### Figma URL format
The URL must contain a node-id for best results:
```
https://www.figma.com/design/FILE_ID/Name?node-id=0-1
```
Select a frame in Figma and copy the link — it will include the node-id automatically.

## How the Agent Works

1. **Fetch** — Calls Figma API to get the design tree (components, colors, typography, layout)
2. **Render** — Renders the Figma node as a PNG for visual context
3. **Analyze** — Sends both JSON structure + image to GPT-4o vision
4. **Generate** — Produces a React component with Tailwind CSS
5. **Validate** — Checks for JSX syntax errors, missing exports, unbalanced tags
6. **Fix** — If errors found, sends back to the model for auto-correction (up to 3 attempts)
7. **Preview** — Renders the component live in Sandpack (in-browser React sandbox)

## Validation Checks

The agent performs these static checks automatically:
- JSX tag balance (open vs close tags)
- `export default` presence
- Brace balance `{ }`
- className/style presence (ensures it's not unstyled)

## Project Structure

```
figma-to-react/
├── start.sh                    # One-command startup
├── backend/
│   ├── main.py                 # FastAPI app + SSE endpoint
│   ├── agent.py                # Agno agent + tools
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── app/
    │   ├── layout.jsx
    │   ├── page.jsx            # Main 3-panel UI
    │   └── globals.css
    ├── components/
    │   └── SandpackPreview.jsx # Live React sandbox
    ├── package.json
    ├── tailwind.config.js
    └── next.config.js
```

## Customization

### Change the LLM model
In `backend/.env`:
```bash
MODEL=gpt-4o
```

You can switch to any OpenAI-compatible model name exposed by your provider.

### Tune generation quality
In `backend/.env`:
```bash
# Lower temperature = more deterministic layouts
MODEL_TEMPERATURE=0.15

# Syntax/structure auto-fix rounds
MAX_RETRIES=3

# Visual fidelity refinement rounds
MAX_FIDELITY_ROUNDS=3

# Minimum target score before refinement stops
TARGET_FIDELITY_SCORE=94

# Context budget for Figma structural summary
MAX_DESIGN_JSON_CHARS=14000
```

The agent also normalizes unreliable image paths to working demo placeholders so large media regions do not render blank in preview.

### Change the base URL (for different providers)
```python
GITHUB_COPILOT_BASE_URL = "https://models.inference.ai.azure.com"
# OpenAI: "https://api.openai.com/v1"
# Azure:  "https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT"
```

### Adjust self-healing retries
```bash
MAX_RETRIES=3
```

## Troubleshooting

**Backend won't start:** Check that `GITHUB_COPILOT_API_KEY` is set in `backend/.env`

**Figma API 403:** Ensure your Figma token has read access to the file

**Preview blank:** Check browser console — the component may have runtime errors. Switch to Code tab and fix manually.

**CORS error:** Make sure the backend is running on port 8000 and frontend on 3000
