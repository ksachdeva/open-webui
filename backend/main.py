from contextlib import asynccontextmanager
import time
import os
import sys
import logging
import mimetypes

from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.webui.routers import (
    auths,
    users,
    chats,
    utils,
)

from apps.ollama.main import router as ollama_router

from apps.webui.internal.db import Session


from config import (
    run_migrations,
    ENV,
    FRONTEND_BUILD_DIR,
    STATIC_DIR,
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
    CORS_ALLOW_ORIGIN,
)

from config import (
    WEBUI_AUTH,
    WEBUI_NAME,
    VERSION,
    DEFAULT_LOCALE,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGIN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auths.router, prefix="/auths", tags=["auths"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(chats.router, prefix="/chats", tags=["chats"])
app.include_router(utils.router, prefix="/utils", tags=["utils"])
app.include_router(ollama_router, prefix="/ollama", tags=["ollama"])

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


@app.get("/")
async def get_status():
    return {"status": True, "auth": WEBUI_AUTH}


@app.get("/config")
async def get_app_config():

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


@app.get("/version")
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


@app.middleware("http")
async def commit_session_after_request(request: Request, call_next):
    response = await call_next(request)
    log.debug("Commit session after request")
    Session.commit()
    return response


@app.middleware("http")
async def check_url(request: Request, call_next):
    start_time = int(time.time())
    response = await call_next(request)
    process_time = int(time.time()) - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
