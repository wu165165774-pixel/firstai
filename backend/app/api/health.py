from fastapi import APIRouter

from app.core.response import success


router = APIRouter()


@router.get("/health")
async def health():

    return success(
        message="NovelForge backend running"
    )