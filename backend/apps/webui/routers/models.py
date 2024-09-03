from fastapi import Depends
from fastapi import APIRouter

from apps.webui.models.models import Models, ModelResponse

from utils.utils import get_verified_user

router = APIRouter()

###########################
# getModels
###########################


@router.get("/", response_model=list[ModelResponse])
async def get_models(user=Depends(get_verified_user)):
    return Models.get_all_models()
