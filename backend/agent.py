import os
import re
import json
import base64
import httpx
from typing import Optional, AsyncGenerator, Any
from openai import AsyncOpenAI

DEFAULT_BASE_URL = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_TEMPERATURE = 0.15
DEFAULT_MAX_DESIGN_JSON_CHARS = 14000
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FIDELITY_ROUNDS = 3
DEFAULT_TARGET_FIDELITY_SCORE = 94
MAX_FIGMA_NODES_IN_SUMMARY = 180
MAX_NODE_DEPTH_IN_SUMMARY = 5
DEFAULT_IMAGE_PLACEHOLDER_URL = "https://picsum.photos/1600/900"
ANCHOR_LEFT_THRESHOLD = 0.38
ANCHOR_RIGHT_THRESHOLD = 0.62

SYSTEM_PROMPT = """You are an expert React + Tailwind implementer.
Your job is to convert the provided design context into a high-fidelity component.

Rules:
- Output ONLY valid JSX code for one default-exported React component
- Use Tailwind CSS classes for styling; avoid inline styles unless strictly necessary
- Import only React (and hooks only if you actually use them)
- Preserve the original layout hierarchy, section ordering, spacing rhythm, and alignments
- Preserve typography scale, weight, and line length as closely as possible
- Preserve horizontal anchoring exactly: if a block is left-anchored in the reference, keep it left; do not recenter it
- Preserve vertical rhythm exactly: heading/subheading/cta spacing should follow the reference proportions
- Keep it responsive while preserving the same composition across screen sizes
- Do not center everything unless the reference is centered
- Do not invent new sections or decorative elements not present in the input
- For image or media areas, always provide a working demo image URL (https://picsum.photos or https://images.unsplash.com)
- Never use local image paths like /image.png, ./image.png, ../image.png, or assets/*
- Keep the component self-contained and renderable in isolation
- Wrap everything in a single root div
- Use plain JavaScript JSX, not TypeScript

Return ONLY the JSX code, no explanation, no markdown fences, no comments outside JSX."""

DESIGN_ANALYSIS_PROMPT = """You are a design analysis assistant.
Use the provided Figma structure and/or screenshot to produce a compact design spec.

Return ONLY valid JSON (no comments, no markdown fences, no trailing commas) using this structure and concrete values:
{
    "canvas": {
        "width": 1440,
        "height": 900,
        "background": "#f3f4f6"
    },
    "sections": [
        {
            "name": "Hero",
            "role": "main",
            "layout": "vertical stack",
            "placement": "top-left",
            "bbox": {"x": 82, "y": 216, "w": 680, "h": 320},
            "norm": {"x": 0.06, "y": 0.24, "w": 0.47, "h": 0.36},
            "x_anchor": "left",
            "key_styles": ["large heading", "muted body copy"],
            "children": [
                {
                    "type": "heading",
                    "text": "Landing page title",
                    "position": "top-left",
                    "size": "large",
                    "bbox": {"x": 82, "y": 216, "w": 560, "h": 92},
                    "norm": {"x": 0.06, "y": 0.24, "w": 0.39, "h": 0.10},
                    "x_anchor": "left",
                    "styles": ["bold", "display"]
                }
            ]
        }
    ],
    "global_tokens": {
        "font_families": ["Inter"],
        "dominant_colors": ["#f3f4f6", "#111111"],
        "radius_values": ["12"],
        "spacing_scale": ["8", "16", "24", "40"]
    },
    "fidelity_priorities": [
        "Preserve primary content block horizontal anchor",
        "Preserve heading/subheading/button spacing",
        "Keep media block proportion and placement"
    ]
}

Guidelines:
- Focus on geometry, spacing, typography, and hierarchy.
- Infer and include left/center/right anchoring for major text blocks and CTA controls.
- Include representative bounding boxes when available so generation can preserve placement.
- Use numeric values where possible. If unknown, use null.
- Keep values concise and useful for code generation.
- Do not include prose outside JSON.
"""

FIX_SYSTEM_PROMPT = """You are a React JSX fixer.
Fix syntax and structural issues while preserving the source design intent.
Return only corrected JSX."""

VALIDATION_PROMPT = """You are fixing a React component.

Errors found:
{errors}

Current code:
{code}

Fix all issues and return corrected JSX only.
Do not add explanations or markdown fences.
"""

FIDELITY_REVIEW_PROMPT = """You are a strict UI fidelity reviewer.
Compare the design context against the generated React JSX.

Return ONLY valid JSON in this format:
{
    "score": 84,
  "differences": [
    {
      "category": "layout|spacing|typography|color|imagery|content",
      "severity": "high|medium|low",
      "issue": "short description",
      "fix": "specific actionable fix"
    }
  ]
}

Rules:
- Score is 0..100 and should be strict.
- Report only meaningful differences.
- Prefer geometry and spacing issues over tiny stylistic nitpicks.
- If a major heading/hero block is centered but should be left (or vice versa), mark as high severity layout issue.
- If an image block is missing or uses local/broken source paths, mark as high severity imagery issue.
- Do not include any text outside JSON.
"""

FIDELITY_FIX_SYSTEM_PROMPT = """You are a React + Tailwind UI refiner.
Apply fidelity fixes so the JSX matches the provided design context better.
Return only updated JSX, with no extra text."""

ANCHOR_FIX_SYSTEM_PROMPT = """You are a React + Tailwind alignment fixer.
Your only job is to correct horizontal anchoring and related container alignment while preserving content and section structure.
Return only updated JSX, no explanations."""


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


def get_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def get_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...truncated..."


def extract_json_object(raw: str) -> Optional[dict[str, Any]]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def fetch_figma_roots(figma_json: dict[str, Any]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []

    nodes = figma_json.get("nodes")
    if isinstance(nodes, dict):
        for node_data in nodes.values():
            if isinstance(node_data, dict) and isinstance(node_data.get("document"), dict):
                roots.append(node_data["document"])

    document = figma_json.get("document")
    if isinstance(document, dict):
        roots.append(document)

    return roots


def format_number(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "?"
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}"


def format_color(color: dict[str, Any], opacity: Optional[float] = None) -> Optional[str]:
    if not isinstance(color, dict):
        return None

    def clamp(v: Any) -> float:
        if not isinstance(v, (int, float)):
            return 0.0
        return max(0.0, min(1.0, float(v)))

    r = int(round(clamp(color.get("r")) * 255))
    g = int(round(clamp(color.get("g")) * 255))
    b = int(round(clamp(color.get("b")) * 255))
    a = 1.0 if opacity is None else clamp(opacity)

    if a < 0.999:
        return f"rgba({r}, {g}, {b}, {a:.2f})"
    return f"#{r:02X}{g:02X}{b:02X}"


def first_solid_fill(fills: Any) -> Optional[str]:
    if not isinstance(fills, list):
        return None
    for paint in fills:
        if not isinstance(paint, dict):
            continue
        if paint.get("type") != "SOLID":
            continue
        if paint.get("visible") is False:
            continue
        color = format_color(paint.get("color") or {}, paint.get("opacity"))
        if color:
            return color
    return None


def summarize_node_line(node: dict[str, Any], depth: int) -> str:
    indent = "  " * depth
    node_type = str(node.get("type") or "NODE")
    node_name = str(node.get("name") or "unnamed")

    parts = [f"{indent}- {node_type} | name={node_name}"]

    bbox = node.get("absoluteBoundingBox")
    if isinstance(bbox, dict):
        x = format_number(bbox.get("x"))
        y = format_number(bbox.get("y"))
        w = format_number(bbox.get("width"))
        h = format_number(bbox.get("height"))
        parts.append(f"bbox=({x},{y},{w}x{h})")

    layout_mode = node.get("layoutMode")
    if isinstance(layout_mode, str) and layout_mode:
        parts.append(f"layout={layout_mode}")

    item_spacing = node.get("itemSpacing")
    if isinstance(item_spacing, (int, float)):
        parts.append(f"gap={format_number(item_spacing)}")

    paddings = [
        node.get("paddingTop"),
        node.get("paddingRight"),
        node.get("paddingBottom"),
        node.get("paddingLeft"),
    ]
    if any(isinstance(v, (int, float)) for v in paddings):
        p = [format_number(v) if isinstance(v, (int, float)) else "?" for v in paddings]
        parts.append(f"padding=({p[0]},{p[1]},{p[2]},{p[3]})")

    text = node.get("characters")
    if isinstance(text, str) and text.strip():
        compact_text = re.sub(r"\s+", " ", text).strip()
        parts.append(f"text='{truncate_text(compact_text, 90)}'")

    style = node.get("style")
    if isinstance(style, dict):
        font_family = style.get("fontFamily")
        font_size = style.get("fontSize")
        font_weight = style.get("fontWeight")
        if font_family or font_size or font_weight:
            font_bits = [
                f"family={font_family}" if font_family else None,
                f"size={format_number(font_size)}" if isinstance(font_size, (int, float)) else None,
                f"weight={font_weight}" if isinstance(font_weight, (int, float)) else None,
            ]
            parts.append("font(" + ",".join(bit for bit in font_bits if bit) + ")")

    fill_color = first_solid_fill(node.get("fills"))
    if fill_color:
        parts.append(f"fill={fill_color}")

    radius = node.get("cornerRadius")
    if isinstance(radius, (int, float)):
        parts.append(f"radius={format_number(radius)}")

    return " | ".join(parts)


def summarize_figma_json(figma_json: dict[str, Any], max_chars: int) -> str:
    roots = fetch_figma_roots(figma_json)
    if not roots:
        return truncate_text(json.dumps(figma_json, ensure_ascii=True), max_chars)

    lines = ["Figma structural summary:"]
    char_budget = len(lines[0]) + 1
    visited = 0
    queue: list[tuple[dict[str, Any], int]] = [(root, 0) for root in roots]

    while queue and visited < MAX_FIGMA_NODES_IN_SUMMARY:
        node, depth = queue.pop(0)
        if depth > MAX_NODE_DEPTH_IN_SUMMARY:
            continue

        line = summarize_node_line(node, depth)
        projected = char_budget + len(line) + 1
        if projected > max_chars:
            lines.append("...summary truncated to stay within context budget...")
            break

        lines.append(line)
        char_budget = projected
        visited += 1

        children = node.get("children")
        if isinstance(children, list) and children:
            limited_children = children[:14]
            for child in limited_children:
                if isinstance(child, dict):
                    queue.append((child, depth + 1))
            if len(children) > len(limited_children):
                overflow = len(children) - len(limited_children)
                overflow_line = f"{'  ' * (depth + 1)}- ...{overflow} more siblings omitted..."
                if char_budget + len(overflow_line) + 1 <= max_chars:
                    lines.append(overflow_line)
                    char_budget += len(overflow_line) + 1

    if visited >= MAX_FIGMA_NODES_IN_SUMMARY:
        tail = "...node limit reached; deeper structure omitted..."
        if char_budget + len(tail) + 1 <= max_chars:
            lines.append(tail)

    return "\n".join(lines)


def build_messages(
    figma_json: Optional[dict[str, Any]],
    image_bytes: Optional[bytes],
    image_media_type: str,
    max_design_json_chars: int,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []

    if figma_json:
        summary = summarize_figma_json(figma_json, max_design_json_chars)
        content.append({
            "type": "text",
            "text": f"Design structure from Figma:\n\n{summary}",
        })

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_media_type};base64,{b64}"},
        })
        content.append({
            "type": "text",
            "text": (
                "Use the screenshot as visual source of truth and the structure data as geometry support. "
                "Match section positions, spacing, typographic scale, and proportions. "
                "Do not use a fixed template."
            ),
        })
    else:
        content.append({
            "type": "text",
            "text": (
                "No screenshot provided. Reconstruct the UI from structure data faithfully, "
                "keeping relative spacing and hierarchy without default template assumptions."
            ),
        })

    return [{"role": "user", "content": content}]


def extract_code(raw: str) -> str:
    """Strip markdown fences if model adds them."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:jsx?|tsx?|react)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def is_reliable_image_src(src: str) -> bool:
    normalized = src.strip().lower()
    if not normalized:
        return False
    return normalized.startswith("https://") or normalized.startswith("http://") or normalized.startswith("data:image/")


def image_source_issues(code: str) -> list[str]:
    issues: list[str] = []

    literal_sources = re.findall(r"<img\\b[^>]*\\bsrc\\s*=\\s*['\"]([^'\"]+)['\"]", code, flags=re.IGNORECASE)
    for src in literal_sources:
        if not is_reliable_image_src(src):
            issues.append(
                f"Image source '{truncate_text(src, 64)}' is not a reliable URL. Use an https:// or data:image source."
            )
        if len(issues) >= 3:
            break

    if len(issues) < 3:
        expression_sources = re.findall(r"<img\\b[^>]*\\bsrc\\s*=\\s*\\{([^}]*)\\}", code, flags=re.IGNORECASE)
        for expr in expression_sources:
            normalized_expr = expr.strip().lower()
            if "http" in normalized_expr or "data:image" in normalized_expr:
                continue
            issues.append("Image source uses dynamic expression without a guaranteed URL. Prefer a stable demo image URL.")
            if len(issues) >= 3:
                break

    return issues


def replace_unreliable_image_sources(code: str) -> tuple[str, int]:
    replacements = 0

    def replace_literal(match: re.Match[str]) -> str:
        nonlocal replacements
        quote = match.group(1)
        src = match.group(2)
        if is_reliable_image_src(src):
            return match.group(0)
        replacements += 1
        return f"src={quote}{DEFAULT_IMAGE_PLACEHOLDER_URL}{quote}"

    def replace_expression(match: re.Match[str]) -> str:
        nonlocal replacements
        expression = (match.group(1) or "").strip().lower()
        if "http" in expression or "data:image" in expression:
            return match.group(0)
        replacements += 1
        return f'src="{DEFAULT_IMAGE_PLACEHOLDER_URL}"'

    updated = re.sub(r"src\\s*=\\s*(['\"])([^'\"]*)\\1", replace_literal, code)
    updated = re.sub(r"src\\s*=\\s*\\{([^}]*)\\}", replace_expression, updated)
    return updated, replacements


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
        errors.append("JSX tags appear unbalanced - possible unclosed elements.")

    if "export default" not in code:
        errors.append("Missing 'export default' - component will not be importable.")

    if "className=" not in code and "style=" not in code:
        errors.append("No className or style found - component may be unstyled.")

    open_braces = code.count("{")
    close_braces = code.count("}")
    if open_braces != close_braces:
        errors.append(f"Unbalanced braces: {open_braces} opening vs {close_braces} closing.")

    errors.extend(image_source_issues(code))

    return errors


def normalize_review(review: Optional[dict[str, Any]]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"score": None, "differences": []}
    if not isinstance(review, dict):
        return normalized

    score = review.get("score")
    if isinstance(score, (int, float)):
        normalized["score"] = int(max(0, min(100, round(float(score)))))

    differences = review.get("differences")
    if not isinstance(differences, list):
        differences = review.get("issues")
    if not isinstance(differences, list):
        differences = []

    cleaned: list[dict[str, str]] = []
    for diff in differences[:12]:
        if not isinstance(diff, dict):
            continue

        issue = str(diff.get("issue") or "").strip()
        if not issue:
            continue

        severity = str(diff.get("severity") or "medium").strip().lower()
        if severity not in {"high", "medium", "low"}:
            severity = "medium"

        category = str(diff.get("category") or "layout").strip().lower()
        fix = str(diff.get("fix") or "").strip()

        cleaned.append({
            "category": category,
            "severity": severity,
            "issue": issue,
            "fix": fix,
        })

    normalized["differences"] = cleaned
    return normalized


def as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def anchor_from_x_ratio(x_ratio: Any) -> Optional[str]:
    ratio = as_float(x_ratio)
    if ratio is None:
        return None
    if ratio <= ANCHOR_LEFT_THRESHOLD:
        return "left"
    if ratio >= ANCHOR_RIGHT_THRESHOLD:
        return "right"
    return "center"


def infer_anchor_from_norm_or_bbox(
    node: dict[str, Any],
    canvas_width: Optional[float],
) -> Optional[str]:
    norm = node.get("norm")
    if isinstance(norm, dict):
        norm_x = as_float(norm.get("x"))
        norm_w = as_float(norm.get("w"))
        if norm_x is not None:
            norm_center = norm_x + (norm_w or 0.0) / 2.0
            anchor = anchor_from_x_ratio(norm_center)
            if anchor:
                return anchor

    bbox = node.get("bbox")
    if isinstance(bbox, dict) and canvas_width and canvas_width > 0:
        x = as_float(bbox.get("x"))
        w = as_float(bbox.get("w"))
        if x is not None:
            center = x + (w or 0.0) / 2.0
            return anchor_from_x_ratio(center / canvas_width)

    return None


def infer_primary_anchor_from_figma_json(figma_json: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(figma_json, dict):
        return None

    roots = fetch_figma_roots(figma_json)
    if not roots:
        return None

    root_bbox = roots[0].get("absoluteBoundingBox") if isinstance(roots[0], dict) else None
    canvas_width = as_float(root_bbox.get("width")) if isinstance(root_bbox, dict) else None
    if not canvas_width or canvas_width <= 0:
        return None

    candidates: list[tuple[float, float]] = []
    queue: list[dict[str, Any]] = [root for root in roots if isinstance(root, dict)]

    while queue:
        node = queue.pop(0)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    queue.append(child)

        if str(node.get("type") or "").upper() != "TEXT":
            continue

        text = str(node.get("characters") or "").strip()
        if not text:
            continue

        bbox = node.get("absoluteBoundingBox")
        if not isinstance(bbox, dict):
            continue

        x = as_float(bbox.get("x"))
        w = as_float(bbox.get("width"))
        if x is None:
            continue

        style = node.get("style")
        font_size = as_float(style.get("fontSize")) if isinstance(style, dict) else None
        score = (font_size or 16.0) + min(len(text), 80) * 0.02
        center_ratio = (x + (w or 0.0) / 2.0) / canvas_width
        candidates.append((score, center_ratio))

    if not candidates:
        return None

    _, best_ratio = max(candidates, key=lambda item: item[0])
    return anchor_from_x_ratio(best_ratio)


def infer_primary_text_anchor(design_spec: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(design_spec, dict):
        return None

    sections = design_spec.get("sections")
    if not isinstance(sections, list):
        return None

    fallback_anchor: Optional[str] = None

    for section in sections:
        if not isinstance(section, dict):
            continue

        section_anchor = str(section.get("x_anchor") or "").strip().lower()
        if section_anchor in {"left", "center", "right"} and not fallback_anchor:
            fallback_anchor = section_anchor

        children = section.get("children")
        if not isinstance(children, list):
            continue

        for child in children:
            if not isinstance(child, dict):
                continue

            child_type = str(child.get("type") or "").strip().lower()
            child_text = str(child.get("text") or "").strip()
            child_anchor = str(child.get("x_anchor") or "").strip().lower()

            if child_anchor not in {"left", "center", "right"}:
                child_anchor = section_anchor if section_anchor in {"left", "center", "right"} else ""

            if not child_anchor:
                continue

            if child_text and child_type in {"heading", "title", "h1", "h2", "text", "label"}:
                return child_anchor

    return fallback_anchor


def infer_generated_heading_anchor(code: str) -> Optional[str]:
    heading_match = re.search(r"<h[1-3][^>]*>", code, flags=re.IGNORECASE)
    if not heading_match:
        return None

    heading_tag = heading_match.group(0)
    class_match = re.search(r"className\s*=\s*['\"]([^'\"]+)['\"]", heading_tag)
    if class_match:
        classes = class_match.group(1)
        if "text-left" in classes:
            return "left"
        if "text-center" in classes:
            return "center"
        if "text-right" in classes:
            return "right"

    style_match = re.search(r"textAlign\s*:\s*['\"]?(left|center|right)['\"]?", heading_tag, flags=re.IGNORECASE)
    if style_match:
        return style_match.group(1).lower()

    return None


def apply_rule_based_fidelity_hints(
    review: dict[str, Any],
    design_spec: Optional[dict[str, Any]],
    code: str,
) -> dict[str, Any]:
    expected_anchor = infer_primary_text_anchor(design_spec)
    actual_anchor = infer_generated_heading_anchor(code)

    if expected_anchor and actual_anchor and expected_anchor != actual_anchor:
        issues = review.get("differences")
        if not isinstance(issues, list):
            issues = []
        already_reported = any(
            isinstance(item, dict)
            and "anchor" in str(item.get("issue") or "").lower()
            for item in issues
        )

        if not already_reported:
            issues.append({
                "category": "layout",
                "severity": "high",
                "issue": (
                    f"Primary heading anchor mismatch: expected {expected_anchor}, got {actual_anchor}."
                ),
                "fix": (
                    f"Set heading/text container alignment to {expected_anchor} and preserve original horizontal placement."
                ),
            })
            review["differences"] = issues

            score = review.get("score")
            if isinstance(score, int):
                review["score"] = max(0, score - 12)

    return review


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


class FigmaToReactAgent:
    def __init__(self):
        self.client = get_client()
        self.temperature = get_float_env("MODEL_TEMPERATURE", DEFAULT_TEMPERATURE, 0.0, 1.0)
        self.max_retries = get_int_env("MAX_RETRIES", DEFAULT_MAX_RETRIES, 1, 8)
        self.max_fidelity_rounds = get_int_env("MAX_FIDELITY_ROUNDS", DEFAULT_MAX_FIDELITY_ROUNDS, 0, 5)
        self.target_fidelity_score = get_int_env(
            "TARGET_FIDELITY_SCORE",
            DEFAULT_TARGET_FIDELITY_SCORE,
            85,
            100,
        )
        self.max_design_json_chars = get_int_env(
            "MAX_DESIGN_JSON_CHARS",
            DEFAULT_MAX_DESIGN_JSON_CHARS,
            4000,
            30000,
        )

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
                yield {
                    "type": "log",
                    "step": "figma_fetch",
                    "message": f"Figma data fetched - {len(json.dumps(figma_json))} chars of design structure",
                }

                if not figma_image_bytes:
                    yield {
                        "type": "log",
                        "step": "figma_image",
                        "message": "Rendering Figma node as image for visual context...",
                    }
                    try:
                        figma_image_bytes = await fetch_figma_image(figma_url, figma_token)
                        if figma_image_bytes:
                            yield {
                                "type": "log",
                                "step": "figma_image",
                                "message": "Figma node image rendered successfully",
                            }
                    except Exception as e:
                        yield {
                            "type": "log",
                            "step": "figma_image",
                            "message": f"Could not render image: {e} - continuing with JSON only",
                        }
            except Exception as e:
                yield {
                    "type": "log",
                    "step": "figma_fetch",
                    "message": f"Figma API error: {e} - continuing with uploaded image if available",
                }

        elif figma_url and not figma_token:
            yield {
                "type": "log",
                "step": "figma_fetch",
                "message": "No Figma token provided - skipping API fetch, using image only",
            }

        # Step 2: Build multimodal messages
        yield {"type": "log", "step": "analyze", "message": "Preparing structured design context..."}
        messages = build_messages(
            figma_json,
            figma_image_bytes,
            figma_image_media_type,
            self.max_design_json_chars,
        )

        # Step 3: Build intermediate design spec
        yield {"type": "log", "step": "analyze", "message": "Extracting intermediate design spec..."}
        design_spec = await self._analyze_design_spec(messages)
        if design_spec:
            yield {
                "type": "log",
                "step": "analyze",
                "message": "Intermediate design spec extracted successfully",
            }
        else:
            yield {
                "type": "log",
                "step": "analyze",
                "message": "Design spec extraction failed; continuing with direct generation",
            }

        # Step 4: Generate code
        yield {"type": "log", "step": "generate", "message": "Generating React component with Tailwind CSS..."}
        code = await self._generate_component(messages, design_spec)
        code = extract_code(code)

        code, replaced_sources = replace_unreliable_image_sources(code)
        if replaced_sources:
            yield {
                "type": "log",
                "step": "asset_fix",
                "message": f"Replaced {replaced_sources} unreliable image source(s) with demo placeholders",
            }

        yield {"type": "log", "step": "generate", "message": f"Initial code generated ({len(code)} chars)"}

        # Step 5: Syntax and structure self-healing loop
        for attempt in range(self.max_retries):
            yield {
                "type": "log",
                "step": "validate",
                "message": f"Validating code (attempt {attempt + 1}/{self.max_retries})...",
            }
            errors = simple_validate(code)

            if not errors:
                yield {"type": "log", "step": "validate", "message": "Validation passed - no syntax issues found"}
                break

            yield {
                "type": "log",
                "step": "fix",
                "message": f"Found {len(errors)} issue(s): {'; '.join(errors)}. Auto-fixing...",
            }
            fixed_code = await self._fix_syntax(messages, design_spec, code, errors)
            code = extract_code(fixed_code)

            code, replaced_sources = replace_unreliable_image_sources(code)
            if replaced_sources:
                yield {
                    "type": "log",
                    "step": "asset_fix",
                    "message": f"Adjusted {replaced_sources} image source(s) after syntax fix",
                }

            yield {"type": "log", "step": "fix", "message": f"Code fixed (attempt {attempt + 1})"}

        # Step 6: Visual fidelity refinement loop
        if self.max_fidelity_rounds > 0:
            for round_index in range(self.max_fidelity_rounds):
                round_num = round_index + 1
                yield {
                    "type": "log",
                    "step": "fidelity_review",
                    "message": f"Reviewing visual fidelity (round {round_num}/{self.max_fidelity_rounds})...",
                }

                review = await self._review_fidelity(messages, design_spec, code)
                score = review.get("score")
                differences = review.get("differences", [])
                medium_or_higher = [
                    d for d in differences if d.get("severity") in {"high", "medium"}
                ]

                if not differences or (
                    isinstance(score, int)
                    and score >= self.target_fidelity_score
                    and not medium_or_higher
                ):
                    quality_note = f"score={score}" if isinstance(score, int) else "score=n/a"
                    yield {
                        "type": "log",
                        "step": "fidelity_review",
                        "message": f"Fidelity check passed ({quality_note})",
                    }
                    break

                focus_issues = medium_or_higher if medium_or_higher else differences
                focus_preview = "; ".join(d.get("issue", "") for d in focus_issues[:2])
                score_note = str(score) if isinstance(score, int) else "n/a"

                yield {
                    "type": "log",
                    "step": "fidelity_fix",
                    "message": f"Refining fidelity (score={score_note}). Focus: {focus_preview}",
                }

                revised_code = await self._apply_fidelity_fixes(messages, design_spec, code, review)
                revised_code = extract_code(revised_code)

                revised_code, replaced_sources = replace_unreliable_image_sources(revised_code)
                if replaced_sources:
                    yield {
                        "type": "log",
                        "step": "asset_fix",
                        "message": f"Adjusted {replaced_sources} image source(s) during fidelity refinement",
                    }

                if revised_code.strip() == code.strip():
                    yield {
                        "type": "log",
                        "step": "fidelity_fix",
                        "message": "No further improvements suggested by model; stopping refinement",
                    }
                    break

                code = revised_code

        yield {"type": "log", "step": "done", "message": "Agent complete - sending code to UI"}
        yield {"type": "result", "code": code}

    async def _chat(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "system", "content": system_prompt}] + messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise RuntimeError(f"Model request failed: {exc}") from exc

        return response.choices[0].message.content or ""

    async def _analyze_design_spec(
        self,
        messages: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        content = list(messages[0]["content"])
        content.append({
            "type": "text",
            "text": "Build the compact design spec JSON now.",
        })
        raw = await self._chat(
            DESIGN_ANALYSIS_PROMPT,
            [{"role": "user", "content": content}],
            max_tokens=1600,
            temperature=0.0,
        )
        return extract_json_object(raw)

    async def _generate_component(
        self,
        messages: list[dict[str, Any]],
        design_spec: Optional[dict[str, Any]],
    ) -> str:
        content = list(messages[0]["content"])
        if design_spec:
            spec_json = truncate_text(json.dumps(design_spec, ensure_ascii=True), 5500)
            content.append({
                "type": "text",
                "text": f"Use this intermediate design spec to improve fidelity:\n{spec_json}",
            })
        return await self._chat(
            SYSTEM_PROMPT,
            [{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=self.temperature,
        )

    async def _fix_syntax(
        self,
        messages: list[dict[str, Any]],
        design_spec: Optional[dict[str, Any]],
        code: str,
        errors: list[str],
    ) -> str:
        content = list(messages[0]["content"])
        if design_spec:
            spec_json = truncate_text(json.dumps(design_spec, ensure_ascii=True), 2500)
            content.append({
                "type": "text",
                "text": f"Reference design spec:\n{spec_json}",
            })
        content.append({
            "type": "text",
            "text": VALIDATION_PROMPT.format(
                errors="\n".join(f"- {e}" for e in errors),
                code=code,
            ),
        })
        return await self._chat(
            FIX_SYSTEM_PROMPT,
            [{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=0.0,
        )

    async def _review_fidelity(
        self,
        messages: list[dict[str, Any]],
        design_spec: Optional[dict[str, Any]],
        code: str,
    ) -> dict[str, Any]:
        content = list(messages[0]["content"])
        if design_spec:
            spec_json = truncate_text(json.dumps(design_spec, ensure_ascii=True), 2500)
            content.append({
                "type": "text",
                "text": f"Reference design spec:\n{spec_json}",
            })
        content.append({
            "type": "text",
            "text": (
                "Review this JSX against the design context and return JSON only.\n\n"
                f"JSX:\n{code}"
            ),
        })
        raw = await self._chat(
            FIDELITY_REVIEW_PROMPT,
            [{"role": "user", "content": content}],
            max_tokens=1200,
            temperature=0.0,
        )
        review = normalize_review(extract_json_object(raw))
        return apply_rule_based_fidelity_hints(review, design_spec, code)

    async def _apply_fidelity_fixes(
        self,
        messages: list[dict[str, Any]],
        design_spec: Optional[dict[str, Any]],
        code: str,
        review: dict[str, Any],
    ) -> str:
        content = list(messages[0]["content"])
        if design_spec:
            spec_json = truncate_text(json.dumps(design_spec, ensure_ascii=True), 2500)
            content.append({
                "type": "text",
                "text": f"Reference design spec:\n{spec_json}",
            })

        review_json = truncate_text(json.dumps(review, ensure_ascii=True), 3000)
        content.append({
            "type": "text",
            "text": (
                "Apply the following fidelity fixes to the JSX while keeping it valid and responsive.\n\n"
                f"Fidelity review:\n{review_json}\n\n"
                f"Current JSX:\n{code}"
            ),
        })

        return await self._chat(
            FIDELITY_FIX_SYSTEM_PROMPT,
            [{"role": "user", "content": content}],
            max_tokens=4096,
            temperature=0.1,
        )
