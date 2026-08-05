from fastapi import APIRouter

from app.llm.bootstrap import registry


router = APIRouter()


@router.get("/providers")
async def providers():

    return {
        "code":0,
        "message":"success",
        "data":{
            "providers":
            registry.list()
        }
    }