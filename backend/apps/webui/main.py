from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.webui.routers import (
    auths,
    users,
    chats,
    utils,
)

from config import (
    WEBUI_AUTH,
    CORS_ALLOW_ORIGIN,
)


import logging


app = FastAPI()

log = logging.getLogger(__name__)


app.state.MODELS = {}
app.state.TOOLS = {}
app.state.FUNCTIONS = {}

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


@app.get("/")
async def get_status():
    return {
        "status": True,
        "auth": WEBUI_AUTH,
        "default_prompt_suggestions": app.state.DEFAULT_PROMPT_SUGGESTIONS,
    }
