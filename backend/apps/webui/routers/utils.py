from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel


import markdown
import black


from utils.misc import get_gravatar_url

router = APIRouter()


@router.get("/gravatar")
async def get_gravatar(
    email: str,
):
    return get_gravatar_url(email)


class CodeFormatRequest(BaseModel):
    code: str


@router.post("/code/format")
async def format_code(request: CodeFormatRequest):
    try:
        formatted_code = black.format_str(request.code, mode=black.Mode())
        return {"code": formatted_code}
    except black.NothingChanged:
        return {"code": request.code}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class MarkdownForm(BaseModel):
    md: str


@router.post("/markdown")
async def get_html_from_markdown(
    form_data: MarkdownForm,
):
    return {"html": markdown.markdown(form_data.md)}
