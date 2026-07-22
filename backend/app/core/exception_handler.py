from fastapi import Request

from fastapi.responses import JSONResponse


from app.core.exceptions import NovelForgeException



async def novelforge_exception_handler(
    request: Request,
    exc: NovelForgeException
):

    return JSONResponse(

        status_code=400,

        content={
            "code": exc.code,
            "message": exc.message,
            "data": None
        }
    )