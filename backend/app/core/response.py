from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    NovelForge统一API响应格式
    """

    code: int = 0

    message: str = "OK"

    data: T | None = None



def success(
    data: T | None = None,
    message: str = "OK"
) -> ApiResponse[T]:

    return ApiResponse(
        code=0,
        message=message,
        data=data
    )



def failure(
    code: int,
    message: str,
    data=None
) -> ApiResponse:

    return ApiResponse(
        code=code,
        message=message,
        data=data
    )