import os
import re
import json
import base64
import httpx
from typing import Optional, AsyncGenerator
from openai import AsyncOpenAI

DEFAULT_BASE_URL = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "gpt-4o"

SYSTEM_PROMPT = """You are an expert React developer. Your job is to convert Figma designs into clean, 
production-quality React components using Tailwind CSS.

Rules:
- Output ONLY valid JSX code inside a single React component
- Use Tailwind CSS classes for all styling - no inline styles, no CSS files
- Use functional components with hooks if needed
- Export the component as default
- Use semantic HTML elements (header, nav, main, section, article, footer, button, etc.)
- Make it pixel-perfect to the design
- Add placeholder text/images where needed using picsum.photos or placeholder text
- Do NOT import anything other than React and useState/useEffect if needed
- The component must be self-contained and renderable in isolation
- Wrap everything in a single root div
- Do NOT use TypeScript, use plain JavaScript JSX

Return ONLY the JSX code, no explanation, no markdown fences, no comments outside JSX."""

VALIDATION_PROMPT = """You are a React code reviewer and fixer.

The following React component has errors. Fix ALL errors and return the corrected component.

Errors found:
{errors}

Original code:
{code}

Rules:
- Fix all syntax and runtime errors
- Keep the same visual design intent
- Use only Tailwind CSS
- Return ONLY the fixed JSX code, no explanation, no markdown fences"""


def get_client() -> AsyncOpenAI:
    api_key = os.environ.get("GITHUB_COPILOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GITHUB_COPILOT_API_KEY is not set. Add it to backend/.env.")

    return AsyncOpenAI(
        base_url=os.environ.get("GITHUB_COPILOT_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        api_key=api_key,
    )


def get_model_name() -> str:
    return os.environ.get("MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


async def fetch_figma_data(figma_url: str, figma_token: str) -> dict:
    """Extract file key and fetch Figma file data."""
    match = re.search(r"figma\.com/(?:file|design)/([a-zA-Z0-9]+)", figma_url)
    if not match:
        raise ValueError("Invalid Figma URL. Expected format: https://www.figma.com/file/FILEID/...")
    file_key = match.group(1)

    node_match = re.search(r"node-id=([^&]+)", figma_url)
    node_id = node_match.group(1).replace("-", ":") if node_match else None

    headers = {"X-Figma-Token": figma_token}
    async with httpx.AsyncClient(timeout=30) as client:
        if node_id:
            url = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}"
        else:
            url = f"https://api.figma.com/v1/files/{file_key}"
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_figma_image(figma_url: str, figma_token: str) -> Optional[bytes]:
    """Render a Figma node as an image for vision context."""
    match = re.search(r"figma\.com/(?:file|design)/([a-zA-Z0-9]+)", figma_url)
    if not match:
        return None
    file_key = match.group(1)

    node_match = re.search(r"node-id=([^&]+)", figma_url)
    if not node_match:
        return None
    node_id = node_match.group(1).replace("-", ":")

    headers = {"X-Figma-Token": figma_token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.figma.com/v1/images/{file_key}",
            headers=headers,
            params={"ids": node_id, "format": "png", "scale": 2},
        )
        resp.raise_for_status()
        data = resp.json()
        image_url = list(data.get("images", {}).values())[0] if data.get("images") else None
        if not image_url:
            return None
        img_resp = await client.get(image_url)
        return img_resp.content


def extract_code(raw: str) -> str:
    """Strip markdown fences if model adds them."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:jsx?|tsx?|react)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def build_messages(figma_json: Optional[dict], image_bytes: Optional[bytes], image_media_type: str) -> list:
    content = []

    if figma_json:
        summary = json.dumps(figma_json, indent=2)[:6000]
        content.append({
            "type": "text",
            "text": f"Here is the Figma design data (JSON structure):\n\n{summary}"
        })

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_media_type};base64,{b64}"}
        })
        content.append({
            "type": "text",
            "text": "Convert this Figma design into a React component with Tailwind CSS. Return only the JSX code."
        })
    else:
        content.append({
            "type": "text",
            "text": "Convert this Figma design JSON into a React component with Tailwind CSS. Return only the JSX code."
        })

    return [{"role": "user", "content": content}]


def simple_validate(code: str) -> list[str]:
    """Basic static checks without running Node."""
    errors = []
    if not code.strip():
        errors.append("Generated code is empty.")
        return errors

    open_tags = len(re.findall(r"<[A-Za-z][^/]*[^/]>", code))
    close_tags = len(re.findall(r"</[A-Za-z]", code))
    self_closing = len(re.findall(r"/>", code))
    if abs(open_tags - close_tags - self_closing) > 5:
        errors.append("JSX tags appear unbalanced — possible unclosed elements.")

    if "export default" not in code:
        errors.append("Missing 'export default' — component won't be importable.")

    if "className=" not in code and "style=" not in code:
        errors.append("No className or style found — component may be unstyled.")

    open_braces = code.count("{")
    close_braces = code.count("}")
    if open_braces != close_braces:
        errors.append(f"Unbalanced braces: {open_braces} opening vs {close_braces} closing.")

    return errors


class FigmaToReactAgent:
    def __init__(self):
        self.client = get_client()
        self.max_retries = 3

    async def run(
        self,
        figma_url: Optional[str],
        figma_token: Optional[str],
        image_bytes: Optional[bytes],
        image_media_type: Optional[str],
    ) -> AsyncGenerator[dict, None]:

        yield {"type": "log", "step": "start", "message": "Agent started"}

        figma_json = None
        figma_image_bytes = image_bytes
        figma_image_media_type = image_media_type or "image/png"

        # Step 1: Fetch Figma data if URL provided
        if figma_url and figma_token:
            yield {"type": "log", "step": "figma_fetch", "message": "Fetching Figma design data via API..."}
            try:
                figma_json = await fetch_figma_data(figma_url, figma_token)
                yield {"type": "log", "step": "figma_fetch", "message": f"Figma data fetched — {len(json.dumps(figma_json))} chars of design structure"}

                if not figma_image_bytes:
                    yield {"type": "log", "step": "figma_image", "message": "Rendering Figma node as image for visual context..."}
                    try:
                        figma_image_bytes = await fetch_figma_image(figma_url, figma_token)
                        if figma_image_bytes:
                            yield {"type": "log", "step": "figma_image", "message": "Figma node image rendered successfully"}
                    except Exception as e:
                        yield {"type": "log", "step": "figma_image", "message": f"Could not render image: {e} — continuing with JSON only"}
            except Exception as e:
                yield {"type": "log", "step": "figma_fetch", "message": f"Figma API error: {e} — continuing with uploaded image if available"}

        elif figma_url and not figma_token:
            yield {"type": "log", "step": "figma_fetch", "message": "No Figma token provided — skipping API fetch, using image only"}

        # Step 2: Build messages
        yield {"type": "log", "step": "analyze", "message": "Analyzing design with vision + structure..."}
        messages = build_messages(figma_json, figma_image_bytes, figma_image_media_type)

        # Step 3: Generate code
        yield {"type": "log", "step": "generate", "message": "Generating React component with Tailwind CSS..."}
        code = await self._generate(messages)
        code = extract_code(code)
        yield {"type": "log", "step": "generate", "message": f"Initial code generated ({len(code)} chars)"}

        # Step 4: Self-healing validation loop
        for attempt in range(self.max_retries):
            yield {"type": "log", "step": "validate", "message": f"Validating code (attempt {attempt + 1}/{self.max_retries})..."}
            errors = simple_validate(code)

            if not errors:
                yield {"type": "log", "step": "validate", "message": "Validation passed — no errors found"}
                break

            yield {"type": "log", "step": "fix", "message": f"Found {len(errors)} issue(s): {'; '.join(errors)}. Auto-fixing..."}
            fix_messages = [
                {"role": "user", "content": VALIDATION_PROMPT.format(
                    errors="\n".join(f"- {e}" for e in errors),
                    code=code
                )}
            ]
            code = await self._generate(fix_messages)
            code = extract_code(code)
            yield {"type": "log", "step": "fix", "message": f"Code fixed (attempt {attempt + 1})"}

        yield {"type": "log", "step": "done", "message": "Agent complete — sending code to UI"}
        yield {"type": "result", "code": code}

    async def _generate(self, messages: list) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                max_tokens=4096,
                temperature=0.2,
            )
        except Exception as exc:
            raise RuntimeError(f"Model request failed: {exc}") from exc

        return response.choices[0].message.content or ""
