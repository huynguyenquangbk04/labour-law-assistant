import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Any
from backend.core.llm_services import llm_reasoning_func, EmbeddingFuncWrapper

app = FastAPI()
embedder = EmbeddingFuncWrapper()
DRIFT_ACTION_MARKER = "[[DRIFT_ACTION_JSON]]"


class DriftActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str
    score: int = Field(ge=0, le=100)
    follow_up_queries: list[str]


DRIFT_ACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "DriftActionResponse",
        "strict": True,
        "schema": DriftActionResponse.model_json_schema(),
    },
}


async def _single_text(text: str):
    yield text


def _strip_markdown_code_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    response_format: dict[str, Any] | None = None
    stream: bool = False


async def _stream_response(text_stream: AsyncIterator[str], model: str):
    async for text in text_stream:
        chunk = {
            "id": "chatcmpl-local",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": text},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    messages = [dict(message) for message in req.messages]
    is_drift_action = any(
        isinstance(message.get("content"), str)
        and DRIFT_ACTION_MARKER in message["content"]
        for message in messages
    )
    if is_drift_action:
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = content.replace(DRIFT_ACTION_MARKER, "").strip()

    prompt = messages[-1]["content"]
    history = messages[:-1]
    response_format = (
        DRIFT_ACTION_RESPONSE_FORMAT if is_drift_action else req.response_format
    )

    text = await llm_reasoning_func(
        prompt,
        history=history,
        stream=req.stream and not is_drift_action,
        response_format=response_format,
    )
    if is_drift_action:
        cleaned_text = _strip_markdown_code_fence(text or "")
        try:
            text = DriftActionResponse.model_validate_json(cleaned_text).model_dump_json()
        except Exception:
            # Fallback if LLM outputted non-JSON or empty
            text = DriftActionResponse(
                response=cleaned_text or "No response generated.",
                score=50,
                follow_up_queries=[]
            ).model_dump_json()

    if req.stream:
        return StreamingResponse(
            _stream_response(
                _single_text(text) if is_drift_action else text,
                req.model,
            ),
            media_type="text/event-stream",
        )

    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "model": req.model,  # << BẮT BUỘC — thiếu field này gây lỗi "model: Input should be a valid string"
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class EmbedRequest(BaseModel):
    model: str
    input: list[str] | str


@app.post("/v1/embeddings")
async def embeddings(req: EmbedRequest):
    texts = [req.input] if isinstance(req.input, str) else req.input
    vectors = await embedder(texts)
    return {
        "object": "list",
        "model": req.model,  # << BẮT BUỘC — tương tự chat_completions, tránh lỗi tương tự cho embedding
        "data": [
            {"object": "embedding", "index": i, "embedding": v.tolist()}
            for i, v in enumerate(vectors)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.get("/health")
async def health():
    return {"status": "ok"}