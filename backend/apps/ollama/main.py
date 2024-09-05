from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, ConfigDict


import re
import json
import aiohttp
import asyncio
import logging
import time
from typing import Optional, Union

from starlette.background import BackgroundTask

from constants import ERROR_MESSAGES
from utils.utils import get_verified_user


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
    else:
        pass

    response = await call_next(request)
    return response


@app.head("/")
@app.get("/")
async def get_status():
    return {"status": True}


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


class GenerateCompletionForm(BaseModel):
    model: str
    prompt: str
    images: Optional[list[str]] = None
    format: Optional[str] = None
    options: Optional[dict] = None
    system: Optional[str] = None
    template: Optional[str] = None
    context: Optional[str] = None
    stream: Optional[bool] = True
    raw: Optional[bool] = None
    keep_alive: Optional[Union[int, str]] = None


@app.post("/api/generate")
async def generate_completion(
    form_data: GenerateCompletionForm,
    user=Depends(get_verified_user),
):

    model = form_data.model

    if ":" not in model:
        model = f"{model}:latest"

    if model not in app.state.MODELS:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(form_data.model),
        )

    url = app.state.OLLAMA_BASE_URL
    log.info(f"url: {url}")

    return await post_streaming_url(
        f"{url}/api/generate", form_data.model_dump_json(exclude_none=True).encode()
    )


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


def get_ollama_url(model: str):
    if model not in app.state.MODELS:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(model),
        )

    url = app.state.OLLAMA_BASE_URL
    return url


@app.post("/api/chat")
async def generate_chat_completion(
    form_data: GenerateChatCompletionForm,
    user=Depends(get_verified_user),
):
    payload = {**form_data.model_dump(exclude_none=True)}
    log.debug(f"{payload = }")
    if "metadata" in payload:
        del payload["metadata"]

    if ":" not in payload["model"]:
        payload["model"] = f"{payload['model']}:latest"

    url = get_ollama_url(payload["model"])
    log.info(f"url: {url}")
    log.debug(payload)

    return await post_streaming_url(
        f"{url}/api/chat", json.dumps(payload), content_type="application/x-ndjson"
    )


# TODO: we should update this part once Ollama supports other types
class OpenAIChatMessageContent(BaseModel):
    type: str
    model_config = ConfigDict(extra="allow")


class OpenAIChatMessage(BaseModel):
    role: str
    content: Union[str, OpenAIChatMessageContent]

    model_config = ConfigDict(extra="allow")


class OpenAIChatCompletionForm(BaseModel):
    model: str
    messages: list[OpenAIChatMessage]

    model_config = ConfigDict(extra="allow")


@app.post("/v1/chat/completions")
async def generate_openai_chat_completion(
    form_data: dict,
    user=Depends(get_verified_user),
):
    completion_form = OpenAIChatCompletionForm(**form_data)
    payload = {**completion_form.model_dump(exclude_none=True, exclude=["metadata"])}
    if "metadata" in payload:
        del payload["metadata"]

    if ":" not in payload["model"]:
        payload["model"] = f"{payload['model']}:latest"

    url = get_ollama_url(payload["model"])
    log.info(f"url: {url}")

    return await post_streaming_url(
        f"{url}/v1/chat/completions",
        json.dumps(payload),
        stream=payload.get("stream", False),
    )


@app.get("/v1/models")
async def get_openai_models(
    user=Depends(get_verified_user),
):
    models = await get_all_models()
    return {
        "data": [
            {
                "id": model["model"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openai",
            }
            for model in models["models"]
        ],
        "object": "list",
    }
