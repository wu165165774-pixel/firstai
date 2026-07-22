import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import logger



class RequestLogMiddleware(
    BaseHTTPMiddleware
):


    async def dispatch(
        self,
        request,
        call_next
    ):

        request_id = str(uuid.uuid4())


        start = time.time()


        logger.info(
            f"[{request_id}] "
            f"{request.method} "
            f"{request.url}"
        )


        response = await call_next(request)


        cost = time.time() - start


        logger.info(
            f"[{request_id}] "
            f"finished "
            f"{cost:.3f}s"
        )


        response.headers[
            "X-Request-ID"
        ] = request_id


        return response