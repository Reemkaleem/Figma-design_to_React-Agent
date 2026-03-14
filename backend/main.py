from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json
import asyncio
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from agent import FigmaToReactAgent

load_dotenv(Path(__file__).with_name(".env"))

app = FastAPI(title="Figma to React Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = FigmaToReactAgent()


@app.post("/generate")
async def generate_react_code(
    figma_url: Optional[str] = Form(None),
    figma_token: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    if not figma_url and not image:
        raise HTTPException(status_code=400, detail="Provide at least a Figma URL or an image.")

    image_bytes = None
    image_media_type = None
    if image:
        image_bytes = await image.read()
        image_media_type = image.content_type or "image/png"

    async def event_stream():
        try:
            async for event in agent.run(
                figma_url=figma_url,
                figma_token=figma_token,
                image_bytes=image_bytes,
                image_media_type=image_media_type,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"status": "ok"}
