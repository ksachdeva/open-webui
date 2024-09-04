from contextlib import asynccontextmanager
import json
import time
import os
import sys
import logging
import aiohttp
import mimetypes
from typing import Optional

from fastapi import FastAPI, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse, Response


from apps.socket.main import app as socket_app, get_event_emitter, get_event_call
from apps.ollama.main import (
    app as ollama_app,
    get_all_models as get_ollama_models,
    generate_openai_chat_completion as generate_ollama_chat_completion,
)


from apps.webui.main import app as webui_app
from apps.webui.internal.db import Session


from pydantic import BaseModel

from apps.webui.models.users import Users


from utils.utils import (
    get_admin_user,
    get_verified_user,
    get_current_user,
    get_http_authorization_cred,
    decode_token,
)


from config import (
    run_migrations,
    WEBUI_NAME,
    WEBUI_URL,
    WEBUI_AUTH,
    ENV,
    VERSION,
    FRONTEND_BUILD_DIR,
    CACHE_DIR,
    STATIC_DIR,
    DEFAULT_LOCALE,
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
    ENABLE_ADMIN_EXPORT,
    WEBUI_BUILD_HASH,
    SAFE_MODE,
    WEBUI_SECRET_KEY,
    WEBUI_SESSION_COOKIE_SAME_SITE,
    WEBUI_SESSION_COOKIE_SECURE,
    ENABLE_ADMIN_CHAT_ACCESS,
    AppConfig,
    CORS_ALLOW_ORIGIN,
)

from constants import ERROR_MESSAGES

if SAFE_MODE:
    print("SAFE MODE ENABLED")


logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            else:
                raise ex


print(
    rf"""
  ___                    __        __   _     _   _ ___ 
 / _ \ _ __   ___ _ __   \ \      / /__| |__ | | | |_ _|
| | | | '_ \ / _ \ '_ \   \ \ /\ / / _ \ '_ \| | | || | 
| |_| | |_) |  __/ | | |   \ V  V /  __/ |_) | |_| || | 
 \___/| .__/ \___|_| |_|    \_/\_/ \___|_.__/ \___/|___|
      |_|                                               

      
v{VERSION} - building the best open-source AI user interface.
{f"Commit: {WEBUI_BUILD_HASH}" if WEBUI_BUILD_HASH != "dev-build" else ""}
https://github.com/open-webui/open-webui
"""
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(
    docs_url="/docs" if ENV == "dev" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.config = AppConfig()


app.state.MODELS = {}


##################################
#
# ChatCompletion Middleware
#
##################################


async def get_content_from_response(response) -> Optional[str]:
    content = None
    if hasattr(response, "body_iterator"):
        async for chunk in response.body_iterator:
            data = json.loads(chunk.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]

        # Cleanup any remaining background tasks if necessary
        if response.background is not None:
            await response.background()
    else:
        content = response["choices"][0]["message"]["content"]
    return content


def is_chat_completion_request(request):
    return request.method == "POST" and any(
        endpoint in request.url.path
        for endpoint in ["/ollama/api/chat", "/chat/completions"]
    )


async def get_body_and_model_and_user(request):
    # Read the original request body
    body = await request.body()
    body_str = body.decode("utf-8")
    body = json.loads(body_str) if body_str else {}

    model_id = body["model"]
    if model_id not in app.state.MODELS:
        raise Exception("Model not found")
    model = app.state.MODELS[model_id]

    user = get_current_user(
        request,
        get_http_authorization_cred(request.headers.get("Authorization")),
    )

    return body, model, user


class ChatCompletionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_chat_completion_request(request):
            return await call_next(request)
        log.debug(f"request.url.path: {request.url.path}")

        try:
            body, model, user = await get_body_and_model_and_user(request)
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

        extra_params = {
            "__event_emitter__": get_event_emitter(metadata),
            "__event_call__": get_event_call(metadata),
            "__user__": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
            },
        }

        # Initialize data_items to store additional data to be sent to the client
        # Initalize contexts and citation
        data_items = []
        contexts = []
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

        return StreamingResponse(stream_wrapper(response.body_iterator, data_items))

    async def _receive(self, body: bytes):
        return {"type": "http.request", "body": body, "more_body": False}


app.add_middleware(ChatCompletionMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGIN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def commit_session_after_request(request: Request, call_next):
    response = await call_next(request)
    log.debug("Commit session after request")
    Session.commit()
    return response


@app.middleware("http")
async def check_url(request: Request, call_next):
    if len(app.state.MODELS) == 0:
        await get_all_models()
    else:
        pass

    start_time = int(time.time())
    response = await call_next(request)
    process_time = int(time.time()) - start_time
    response.headers["X-Process-Time"] = str(process_time)

    return response


app.mount("/ws", socket_app)
app.mount("/ollama", ollama_app)
app.mount("/api/v1", webui_app)


async def get_all_models():
    # TODO: Optimize this function
    ollama_models = []

    ollama_models = await get_ollama_models()
    ollama_models = [
        {
            "id": model["model"],
            "name": model["name"],
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ollama",
            "ollama": model,
        }
        for model in ollama_models["models"]
    ]

    models = ollama_models

    # custom_models = Models.get_all_models()
    # for custom_model in custom_models:
    #     if custom_model.base_model_id is None:
    #         for model in models:
    #             if (
    #                 custom_model.id == model["id"]
    #                 or custom_model.id == model["id"].split(":")[0]
    #             ):
    #                 model["name"] = custom_model.name
    #                 model["info"] = custom_model.model_dump()

    #                 action_ids = []
    #                 if "info" in model and "meta" in model["info"]:
    #                     action_ids.extend(model["info"]["meta"].get("actionIds", []))

    #                 model["action_ids"] = action_ids
    #     else:
    #         owned_by = "openai"
    #         pipe = None
    #         action_ids = []

    #         for model in models:
    #             if (
    #                 custom_model.base_model_id == model["id"]
    #                 or custom_model.base_model_id == model["id"].split(":")[0]
    #             ):
    #                 owned_by = model["owned_by"]
    #                 if "pipe" in model:
    #                     pipe = model["pipe"]

    #                 if "info" in model and "meta" in model["info"]:
    #                     action_ids.extend(model["info"]["meta"].get("actionIds", []))
    #                 break

    #         models.append(
    #             {
    #                 "id": custom_model.id,
    #                 "name": custom_model.name,
    #                 "object": "model",
    #                 "created": custom_model.created_at,
    #                 "owned_by": owned_by,
    #                 "info": custom_model.model_dump(),
    #                 "preset": True,
    #                 **({"pipe": pipe} if pipe is not None else {}),
    #                 "action_ids": action_ids,
    #             }
    #         )

    app.state.MODELS = {model["id"]: model for model in models}
    webui_app.state.MODELS = app.state.MODELS

    return models


@app.get("/api/models")
async def get_models(user=Depends(get_verified_user)):
    models = await get_all_models()
    return {"data": models}


@app.post("/api/chat/completions")
async def generate_chat_completions(form_data: dict, user=Depends(get_verified_user)):
    model_id = form_data["model"]

    if model_id not in app.state.MODELS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    model = app.state.MODELS[model_id]
    if model["owned_by"] == "ollama":
        return await generate_ollama_chat_completion(form_data, user=user)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )


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


##################################
#
# Config Endpoints
#
##################################


@app.get("/api/config")
async def get_app_config(request: Request):
    user = None
    if "token" in request.cookies:
        token = request.cookies.get("token")
        data = decode_token(token)
        if data is not None and "id" in data:
            user = Users.get_user_by_id(data["id"])

    return {
        "status": True,
        "name": WEBUI_NAME,
        "version": VERSION,
        "default_locale": str(DEFAULT_LOCALE),
        "features": {
            "auth": WEBUI_AUTH,
            "auth_trusted_header": bool(webui_app.state.AUTH_TRUSTED_EMAIL_HEADER),
            "enable_signup": webui_app.state.config.ENABLE_SIGNUP,
            "enable_login_form": webui_app.state.config.ENABLE_LOGIN_FORM,
            **(
                {
                    "enable_image_generation": False,
                    "enable_community_sharing": webui_app.state.config.ENABLE_COMMUNITY_SHARING,
                    "enable_message_rating": webui_app.state.config.ENABLE_MESSAGE_RATING,
                    "enable_admin_export": ENABLE_ADMIN_EXPORT,
                    "enable_admin_chat_access": ENABLE_ADMIN_CHAT_ACCESS,
                }
                if user is not None
                else {}
            ),
        },
        **(
            {
                "default_models": webui_app.state.config.DEFAULT_MODELS,
                "default_prompt_suggestions": webui_app.state.config.DEFAULT_PROMPT_SUGGESTIONS,
                "permissions": {**webui_app.state.config.USER_PERMISSIONS},
            }
            if user is not None
            else {}
        ),
    }


@app.get("/api/config/model/filter")
async def get_model_filter_config(user=Depends(get_admin_user)):
    return {
        "enabled": app.state.config.ENABLE_MODEL_FILTER,
        "models": app.state.config.MODEL_FILTER_LIST,
    }


class ModelFilterConfigForm(BaseModel):
    enabled: bool
    models: list[str]


@app.post("/api/config/model/filter")
async def update_model_filter_config(
    form_data: ModelFilterConfigForm, user=Depends(get_admin_user)
):
    app.state.config.ENABLE_MODEL_FILTER = form_data.enabled
    app.state.config.MODEL_FILTER_LIST = form_data.models

    return {
        "enabled": app.state.config.ENABLE_MODEL_FILTER,
        "models": app.state.config.MODEL_FILTER_LIST,
    }


class UrlForm(BaseModel):
    url: str


@app.get("/api/version")
async def get_app_version():
    return {
        "version": VERSION,
    }


@app.get("/api/version/updates")
async def get_app_latest_release_version():
    try:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                "https://api.github.com/repos/open-webui/open-webui/releases/latest"
            ) as response:
                response.raise_for_status()
                data = await response.json()
                latest_version = data["tag_name"]

                return {"current": VERSION, "latest": latest_version[1:]}
    except aiohttp.ClientError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_MESSAGES.RATE_LIMIT_EXCEEDED,
        )


@app.get("/manifest.json")
async def get_manifest_json():
    return {
        "name": WEBUI_NAME,
        "short_name": WEBUI_NAME,
        "start_url": "/",
        "display": "standalone",
        "background_color": "#343541",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/static/logo.png",
                "type": "image/png",
                "sizes": "500x500",
                "purpose": "any",
            },
            {
                "src": "/static/logo.png",
                "type": "image/png",
                "sizes": "500x500",
                "purpose": "maskable",
            },
        ],
    }


@app.get("/opensearch.xml")
async def get_opensearch_xml():
    xml_content = rf"""
    <OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" xmlns:moz="http://www.mozilla.org/2006/browser/search/">
    <ShortName>{WEBUI_NAME}</ShortName>
    <Description>Search {WEBUI_NAME}</Description>
    <InputEncoding>UTF-8</InputEncoding>
    <Image width="16" height="16" type="image/x-icon">{WEBUI_URL}/static/favicon.png</Image>
    <Url type="text/html" method="get" template="{WEBUI_URL}/?q={"{searchTerms}"}"/>
    <moz:SearchForm>{WEBUI_URL}</moz:SearchForm>
    </OpenSearchDescription>
    """
    return Response(content=xml_content, media_type="application/xml")


@app.get("/health")
async def healthcheck():
    return {"status": True}


@app.get("/health/db")
async def healthcheck_with_db():
    Session.execute(text("SELECT 1;")).all()
    return {"status": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")

if os.path.exists(FRONTEND_BUILD_DIR):
    mimetypes.add_type("text/javascript", ".js")
    app.mount(
        "/",
        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),
        name="spa-static-files",
    )
else:
    log.warning(
        f"Frontend build directory not found at '{FRONTEND_BUILD_DIR}'. Serving API only."
    )
