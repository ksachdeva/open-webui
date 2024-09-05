import os
import logging
from urllib.parse import urlparse

from typing import TypeVar

from pathlib import Path
import shutil


from env import (
    ENV,
    DATA_DIR,
    BACKEND_DIR,
    FRONTEND_BUILD_DIR,
    WEBUI_AUTH,
    log,
    WEBUI_SESSION_COOKIE_SECURE,  # keep this import
    WEBUI_SESSION_COOKIE_SAME_SITE,  # keep this import
    WEBUI_SECRET_KEY,  # keep this import
    GLOBAL_LOG_LEVEL,  # keep this import
    WEBUI_URL,  # keep this import
    WEBUI_NAME,  # keep this import
    WEBUI_FAVICON_URL,  # keep this import
    VERSION,  # keep this import
    SRC_LOG_LEVELS,  # keep this import
)


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/health") == -1


# Filter out /endpoint
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

####################################
# Config helpers
####################################


# Function to run the alembic migrations
def run_migrations():
    print("Running migrations")
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"Error: {e}")


run_migrations()


T = TypeVar("T")


####################################
# WEBUI_AUTH (Required for security)
####################################

JWT_EXPIRES_IN = os.environ.get("JWT_EXPIRES_IN", "-1")


####################################
# Static DIR
####################################

STATIC_DIR = Path(os.getenv("STATIC_DIR", BACKEND_DIR / "static")).resolve()

frontend_favicon = FRONTEND_BUILD_DIR / "static" / "favicon.png"

if frontend_favicon.exists():
    try:
        shutil.copyfile(frontend_favicon, STATIC_DIR / "favicon.png")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
else:
    logging.warning(f"Frontend favicon not found at {frontend_favicon}")

frontend_splash = FRONTEND_BUILD_DIR / "static" / "splash.png"

if frontend_splash.exists():
    try:
        shutil.copyfile(frontend_splash, STATIC_DIR / "splash.png")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
else:
    logging.warning(f"Frontend splash not found at {frontend_splash}")


####################################
# OLLAMA_BASE_URL
####################################


OLLAMA_API_BASE_URL = os.environ.get(
    "OLLAMA_API_BASE_URL", "http://localhost:11434/api"
)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")
AIOHTTP_CLIENT_TIMEOUT = os.environ.get("AIOHTTP_CLIENT_TIMEOUT", "")

if AIOHTTP_CLIENT_TIMEOUT == "":
    AIOHTTP_CLIENT_TIMEOUT = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT = int(AIOHTTP_CLIENT_TIMEOUT)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT = 300


if OLLAMA_BASE_URL == "" and OLLAMA_API_BASE_URL != "":
    OLLAMA_BASE_URL = (
        OLLAMA_API_BASE_URL[:-4]
        if OLLAMA_API_BASE_URL.endswith("/api")
        else OLLAMA_API_BASE_URL
    )

####################################
# WEBUI
####################################

ENABLE_SIGNUP = True

ENABLE_LOGIN_FORM = True

DEFAULT_LOCALE = ""


DEFAULT_USER_ROLE = os.getenv("DEFAULT_USER_ROLE", "pending")


def validate_cors_origins(origins):
    for origin in origins:
        if origin != "*":
            validate_cors_origin(origin)


def validate_cors_origin(origin):
    parsed_url = urlparse(origin)

    # Check if the scheme is either http or https
    if parsed_url.scheme not in ["http", "https"]:
        raise ValueError(
            f"Invalid scheme in CORS_ALLOW_ORIGIN: '{origin}'. Only 'http' and 'https' are allowed."
        )

    # Ensure that the netloc (domain + port) is present, indicating it's a valid URL
    if not parsed_url.netloc:
        raise ValueError(f"Invalid URL structure in CORS_ALLOW_ORIGIN: '{origin}'.")


# For production, you should only need one host as
# fastapi serves the svelte-kit built frontend and backend from the same host and port.
# To test CORS_ALLOW_ORIGIN locally, you can set something like
# CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080
# in your .env file depending on your frontend port, 5173 in this case.
CORS_ALLOW_ORIGIN = os.environ.get("CORS_ALLOW_ORIGIN", "*").split(";")

if "*" in CORS_ALLOW_ORIGIN:
    log.warning(
        "\n\nWARNING: CORS_ALLOW_ORIGIN IS SET TO '*' - NOT RECOMMENDED FOR PRODUCTION DEPLOYMENTS.\n"
    )

validate_cors_origins(CORS_ALLOW_ORIGIN)

SHOW_ADMIN_DETAILS = os.environ.get("SHOW_ADMIN_DETAILS", "true")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", None)
