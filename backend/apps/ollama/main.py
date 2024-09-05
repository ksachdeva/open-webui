import time
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

# from starlette.responses import StreamingResponse
from pydantic import BaseModel


import re
import json
import aiohttp
import asyncio
import logging
from typing import Optional, Union

from starlette.background import BackgroundTask

from utils.utils import get_verified_user
from utils.utils import get_current_user, get_http_authorization_cred

from config import (
    SRC_LOG_LEVELS,
    OLLAMA_BASE_URL,
    AIOHTTP_CLIENT_TIMEOUT,
    CORS_ALLOW_ORIGIN,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OLLAMA"])

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGIN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.OLLAMA_BASE_URL = OLLAMA_BASE_URL
app.state.MODELS = {}


@app.middleware("http")
async def check_url(request: Request, call_next):
    if len(app.state.MODELS) == 0:
        await get_all_models()

    response = await call_next(request)
    return response


async def fetch_url(url):
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url) as response:
                return await response.json()
    except Exception as e:
        # Handle connection error here
        log.error(f"Connection error: {e}")
        return None


async def cleanup_response(
    response: Optional[aiohttp.ClientResponse],
    session: Optional[aiohttp.ClientSession],
):
    if response:
        response.close()
    if session:
        await session.close()


async def post_streaming_url(
    url: str, payload: Union[str, bytes], stream: bool = True, content_type=None
):
    r = None
    try:
        session = aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
        )
        r = await session.post(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()

        if stream:
            headers = dict(r.headers)
            if content_type:
                headers["Content-Type"] = content_type
            return StreamingResponse(
                r.content,
                status_code=r.status,
                headers=headers,
                background=BackgroundTask(
                    cleanup_response, response=r, session=session
                ),
            )
        else:
            res = await r.json()
            await cleanup_response(r, session)
            return res

    except Exception as e:
        error_detail = "Chatty: Server Connection Error"
        if r is not None:
            try:
                res = await r.json()
                if "error" in res:
                    error_detail = f"Ollama: {res['error']}"
            except Exception:
                error_detail = f"Ollama: {e}"

        raise HTTPException(
            status_code=r.status if r else 500,
            detail=error_detail,
        )


def merge_models_lists(model_lists):
    merged_models = {}

    for idx, model_list in enumerate(model_lists):
        if model_list is not None:
            for model in model_list:
                digest = model["digest"]
                if digest not in merged_models:
                    model["urls"] = [idx]
                    merged_models[digest] = model
                else:
                    merged_models[digest]["urls"].append(idx)

    return list(merged_models.values())


async def get_all_models():
    log.info("get_all_models()")

    url = OLLAMA_BASE_URL
    tasks = [fetch_url(f"{url}/api/tags")]
    responses = await asyncio.gather(*tasks)

    models = {
        "models": merge_models_lists(
            map(lambda response: response["models"] if response else None, responses)
        )
    }

    app.state.MODELS = {model["model"]: model for model in models["models"]}

    return models


@app.get("/api/version")
async def get_ollama_versions():

    url = OLLAMA_BASE_URL
    tasks = [fetch_url(f"{url}/api/version")]
    responses = await asyncio.gather(*tasks)
    responses = list(filter(lambda x: x is not None, responses))

    if len(responses) > 0:
        lowest_version = min(
            responses,
            key=lambda x: tuple(
                map(int, re.sub(r"^v|-.*", "", x["version"]).split("."))
            ),
        )

        return {"version": lowest_version["version"]}


class ChatMessage(BaseModel):
    role: str
    content: str
    images: Optional[list[str]] = None


class GenerateChatCompletionForm(BaseModel):
    model: str
    messages: list[ChatMessage]
    format: Optional[str] = None
    options: Optional[dict] = None
    template: Optional[str] = None
    stream: Optional[bool] = None
    keep_alive: Optional[Union[int, str]] = None


@app.post("/api/chat")
async def generate_chat_completion(
    form_data: GenerateChatCompletionForm,
    user=Depends(get_verified_user),
):
    payload = {**form_data.model_dump(exclude_none=True)}
    log.info(f"{payload = }")
    if "metadata" in payload:
        del payload["metadata"]

    if ":" not in payload["model"]:
        payload["model"] = f"{payload['model']}:latest"

    url = OLLAMA_BASE_URL
    log.info(f"url: {url}")
    log.info(payload)

    return await post_streaming_url(
        f"{url}/api/chat", json.dumps(payload), content_type="application/x-ndjson"
    )


@app.get("/api/models")
async def get_models(user=Depends(get_verified_user)):
    models = await get_all_models()

    ollama_models = [
        {
            "id": model["model"],
            "name": model["name"],
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ollama",
            "ollama": model,
        }
        for model in models["models"]
    ]

    return {"data": ollama_models}


@app.post("/api/chat/completed")
async def chat_completed(form_data: dict, user=Depends(get_verified_user)):
    data = form_data
    model_id = data["model"]
    if model_id not in app.state.MODELS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return data


def is_chat_completion_request(request):
    return request.method == "POST" and any(
        endpoint in request.url.path
        for endpoint in ["/ollama/api/chat", "/chat/completions"]
    )


async def get_body_and_user(request):
    # Read the original request body
    body = await request.body()
    body_str = body.decode("utf-8")
    body = json.loads(body_str) if body_str else {}

    user = get_current_user(
        request,
        get_http_authorization_cred(request.headers.get("Authorization")),
    )

    return body, user


class ChatCompletionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_chat_completion_request(request):
            return await call_next(request)
        log.debug(f"request.url.path: {request.url.path}")

        try:
            body, user = await get_body_and_user(request)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": str(e)},
            )

        metadata = {
            "chat_id": body.pop("chat_id", None),
            "message_id": body.pop("id", None),
            "session_id": body.pop("session_id", None),
            "tool_ids": body.get("tool_ids", None),
            "files": body.get("files", None),
        }
        body["metadata"] = metadata

        # Initialize data_items to store additional data to be sent to the client
        # Initalize contexts and citation
        data_items = []
        citations = []

        metadata = {
            **metadata,
            "tool_ids": body.pop("tool_ids", None),
            "files": body.pop("files", None),
        }
        body["metadata"] = metadata

        # If there are citations, add them to the data_items
        if len(citations) > 0:
            data_items.append({"citations": citations})

        modified_body_bytes = json.dumps(body).encode("utf-8")
        # Replace the request body with the modified one
        request._body = modified_body_bytes
        # Set custom header to ensure content-length matches new body length
        request.headers.__dict__["_list"] = [
            (b"content-length", str(len(modified_body_bytes)).encode("utf-8")),
            *[(k, v) for k, v in request.headers.raw if k.lower() != b"content-length"],
        ]

        # making the call to the LLM chat completion
        response = await call_next(request)
        if not isinstance(response, StreamingResponse):
            return response

        content_type = response.headers["Content-Type"]
        is_openai = "text/event-stream" in content_type
        is_ollama = "application/x-ndjson" in content_type
        if not is_openai and not is_ollama:
            return response

        def wrap_item(item):
            return f"data: {item}\n\n" if is_openai else f"{item}\n"

        async def stream_wrapper(original_generator, data_items):
            for item in data_items:
                yield wrap_item(json.dumps(item))

            async for data in original_generator:
                yield data

        return StreamingResponse(
            stream_wrapper(
                response.body_iterator,
                data_items,
            )
        )

    async def _receive(self, body: bytes):
        return {"type": "http.request", "body": body, "more_body": False}


app.add_middleware(ChatCompletionMiddleware)
