from fastapi import FastAPI


from app.config.settings import settings

from app.api.health import router as health_router



app = FastAPI(

    title=settings.app_name,

    version="0.1.0"

)



app.include_router(

    health_router,

    prefix="/api/v1",

    tags=["System"]

)