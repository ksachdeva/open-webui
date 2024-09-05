from contextlib import asynccontextmanager
import json
import time
import os
import sys
import logging
import mimetypes

from fastapi import FastAPI, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse


from apps.ollama.main import (
    app as ollama_app,
    get_all_models as get_ollama_models,
)


from apps.webui.main import app as webui_app
from apps.webui.internal.db import Session


from apps.webui.models.users import Users


from utils.utils import (
    get_verified_user,
    get_current_user,
    get_http_authorization_cred,
    decode_token,
)


from config import (
    run_migrations,
    WEBUI_NAME,
    WEBUI_AUTH,
    ENV,
    VERSION,
    FRONTEND_BUILD_DIR,
    STATIC_DIR,
    DEFAULT_LOCALE,
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
    CORS_ALLOW_ORIGIN,
    ENABLE_LOGIN_FORM,
    ENABLE_SIGNUP,
)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(
    docs_url="/docs" if ENV == "dev" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.MODELS = {}


##################################
#
# ChatCompletion Middleware
#
##################################


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

    start_time = int(time.time())
    response = await call_next(request)
    process_time = int(time.time()) - start_time
    response.headers["X-Process-Time"] = str(process_time)

    return response


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

    app.state.MODELS = {model["id"]: model for model in models}
    webui_app.state.MODELS = app.state.MODELS

    return models


@app.get("/api/models")
async def get_models(user=Depends(get_verified_user)):
    models = await get_all_models()
    return {"data": models}


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
            "enable_signup": ENABLE_SIGNUP,
            "enable_login_form": ENABLE_LOGIN_FORM,
        },
    }


@app.get("/api/version")
async def get_app_version():
    return {
        "version": VERSION,
    }


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


@app.get("/health")
async def healthcheck():
    return {"status": True}


@app.get("/health/db")
async def healthcheck_with_db():
    Session.execute(text("SELECT 1;")).all()
    return {"status": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
