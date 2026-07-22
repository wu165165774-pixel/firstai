from app.core.errors import ErrorCode



class NovelForgeException(Exception):
    """
    NovelForge业务异常基类
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str
    ):

        self.code = code

        self.message = message

        super().__init__(message)