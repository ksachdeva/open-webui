from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, ConfigDict


import re
import random
import requests
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
    OLLAMA_BASE_URLS,
    AIOHTTP_CLIENT_TIMEOUT,
    AppConfig,
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

app.state.config = AppConfig()
app.state.config.OLLAMA_BASE_URLS = OLLAMA_BASE_URLS
app.state.MODELS = {}


# TODO: Implement a more intelligent load balancing mechanism for distributing requests among multiple backend instances.
# Current implementation uses a simple round-robin approach (random.choice). Consider incorporating algorithms like weighted round-robin,
# least connections, or least response time for better resource utilization and performance optimization.


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
        error_detail = "Open WebUI: Server Connection Error"
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

    tasks = [fetch_url(f"{url}/api/tags") for url in app.state.config.OLLAMA_BASE_URLS]
    responses = await asyncio.gather(*tasks)

    models = {
        "models": merge_models_lists(
            map(lambda response: response["models"] if response else None, responses)
        )
    }

    app.state.MODELS = {model["model"]: model for model in models["models"]}

    return models


@app.get("/api/tags")
@app.get("/api/tags/{url_idx}")
async def get_ollama_tags(
    url_idx: Optional[int] = None, user=Depends(get_verified_user)
):
    if url_idx is None:
        models = await get_all_models()
        return models
    else:
        url = app.state.config.OLLAMA_BASE_URLS[url_idx]

        r = None
        try:
            r = requests.request(method="GET", url=f"{url}/api/tags")
            r.raise_for_status()

            return r.json()
        except Exception as e:
            log.exception(e)
            error_detail = "Open WebUI: Server Connection Error"
            if r is not None:
                try:
                    res = r.json()
                    if "error" in res:
                        error_detail = f"Ollama: {res['error']}"
                except Exception:
                    error_detail = f"Ollama: {e}"

            raise HTTPException(
                status_code=r.status_code if r else 500,
                detail=error_detail,
            )


@app.get("/api/version")
@app.get("/api/version/{url_idx}")
async def get_ollama_versions(url_idx: Optional[int] = None):

    if url_idx is None:
        # returns lowest version
        tasks = [
            fetch_url(f"{url}/api/version") for url in app.state.config.OLLAMA_BASE_URLS
        ]
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
        else:
            raise HTTPException(
                status_code=500,
                detail=ERROR_MESSAGES.OLLAMA_NOT_FOUND,
            )
    else:
        url = app.state.config.OLLAMA_BASE_URLS[url_idx]

        r = None
        try:
            r = requests.request(method="GET", url=f"{url}/api/version")
            r.raise_for_status()

            return r.json()
        except Exception as e:
            log.exception(e)
            error_detail = "Open WebUI: Server Connection Error"
            if r is not None:
                try:
                    res = r.json()
                    if "error" in res:
                        error_detail = f"Ollama: {res['error']}"
                except Exception:
                    error_detail = f"Ollama: {e}"

            raise HTTPException(
                status_code=r.status_code if r else 500,
                detail=error_detail,
            )


class ModelNameForm(BaseModel):
    name: str


@app.post("/api/show")
async def show_model_info(form_data: ModelNameForm, user=Depends(get_verified_user)):
    if form_data.name not in app.state.MODELS:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.MODEL_NOT_FOUND(form_data.name),
        )

    url_idx = random.choice(app.state.MODELS[form_data.name]["urls"])
    url = app.state.config.OLLAMA_BASE_URLS[url_idx]
    log.info(f"url: {url}")

    r = requests.request(
        method="POST",
        url=f"{url}/api/show",
        headers={"Content-Type": "application/json"},
        data=form_data.model_dump_json(exclude_none=True).encode(),
    )
    try:
        r.raise_for_status()

        return r.json()
    except Exception as e:
        log.exception(e)
        error_detail = "Open WebUI: Server Connection Error"
        if r is not None:
            try:
                res = r.json()
                if "error" in res:
                    error_detail = f"Ollama: {res['error']}"
            except Exception:
                error_detail = f"Ollama: {e}"

        raise HTTPException(
            status_code=r.status_code if r else 500,
            detail=error_detail,
        )


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
@app.post("/api/generate/{url_idx}")
async def generate_completion(
    form_data: GenerateCompletionForm,
    url_idx: Optional[int] = None,
    user=Depends(get_verified_user),
):
    if url_idx is None:
        model = form_data.model

        if ":" not in model:
            model = f"{model}:latest"

        if model in app.state.MODELS:
            url_idx = random.choice(app.state.MODELS[model]["urls"])
        else:
            raise HTTPException(
                status_code=400,
                detail=ERROR_MESSAGES.MODEL_NOT_FOUND(form_data.model),
            )

    url = app.state.config.OLLAMA_BASE_URLS[url_idx]
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


def get_ollama_url(url_idx: Optional[int], model: str):
    if url_idx is None:
        if model not in app.state.MODELS:
            raise HTTPException(
                status_code=400,
                detail=ERROR_MESSAGES.MODEL_NOT_FOUND(model),
            )
        url_idx = random.choice(app.state.MODELS[model]["urls"])
    url = app.state.config.OLLAMA_BASE_URLS[url_idx]
    return url


@app.post("/api/chat")
@app.post("/api/chat/{url_idx}")
async def generate_chat_completion(
    form_data: GenerateChatCompletionForm,
    url_idx: Optional[int] = None,
    user=Depends(get_verified_user),
):
    payload = {**form_data.model_dump(exclude_none=True)}
    log.debug(f"{payload = }")
    if "metadata" in payload:
        del payload["metadata"]

    model_id = form_data.model

    if ":" not in payload["model"]:
        payload["model"] = f"{payload['model']}:latest"

    url = get_ollama_url(url_idx, payload["model"])
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
@app.post("/v1/chat/completions/{url_idx}")
async def generate_openai_chat_completion(
    form_data: dict,
    url_idx: Optional[int] = None,
    user=Depends(get_verified_user),
):
    completion_form = OpenAIChatCompletionForm(**form_data)
    payload = {**completion_form.model_dump(exclude_none=True, exclude=["metadata"])}
    if "metadata" in payload:
        del payload["metadata"]

    model_id = completion_form.model

    if app.state.config.ENABLE_MODEL_FILTER:
        if user.role == "user" and model_id not in app.state.config.MODEL_FILTER_LIST:
            raise HTTPException(
                status_code=403,
                detail="Model not found",
            )

    if ":" not in payload["model"]:
        payload["model"] = f"{payload['model']}:latest"

    url = get_ollama_url(url_idx, payload["model"])
    log.info(f"url: {url}")

    return await post_streaming_url(
        f"{url}/v1/chat/completions",
        json.dumps(payload),
        stream=payload.get("stream", False),
    )


@app.get("/v1/models")
@app.get("/v1/models/{url_idx}")
async def get_openai_models(
    url_idx: Optional[int] = None,
    user=Depends(get_verified_user),
):
    if url_idx is None:
        models = await get_all_models()

        if app.state.config.ENABLE_MODEL_FILTER:
            if user.role == "user":
                models["models"] = list(
                    filter(
                        lambda model: model["name"]
                        in app.state.config.MODEL_FILTER_LIST,
                        models["models"],
                    )
                )

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

    else:
        url = app.state.config.OLLAMA_BASE_URLS[url_idx]
        try:
            r = requests.request(method="GET", url=f"{url}/api/tags")
            r.raise_for_status()

            models = r.json()

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

        except Exception as e:
            log.exception(e)
            error_detail = "Open WebUI: Server Connection Error"
            if r is not None:
                try:
                    res = r.json()
                    if "error" in res:
                        error_detail = f"Ollama: {res['error']}"
                except Exception:
                    error_detail = f"Ollama: {e}"

            raise HTTPException(
                status_code=r.status_code if r else 500,
                detail=error_detail,
            )
