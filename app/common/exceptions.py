"""
统一异常体系
所有业务异常继承 PipelineRAGBaseException，通过 code 区分错误类型。
"""


class BaseCode:
    """全局标准错误码——业务异常统一从这里引用"""

    SUCCESS = 0
    BAD_REQUEST = 10054  # 参数校验失败
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    SYSTEM_ERROR = -1  # 未知系统错误


class PipelineRAGBaseException(Exception):
    """全局基础异常"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class PipelineRAGFrameException(PipelineRAGBaseException):
    """框架级业务异常"""

    def __init__(self, code: int, message: str):
        super().__init__(code, message)


class ArgumentException(PipelineRAGBaseException):
    """参数校验异常"""

    def __init__(self, message: str, errors: list[dict[str, str]] | None = None):
        super().__init__(BaseCode.BAD_REQUEST, message)
        self.errors = errors or []


class AuthException(PipelineRAGBaseException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(BaseCode.UNAUTHORIZED, message)


class RateLimitException(PipelineRAGBaseException):
    def __init__(self, message: str = "Too Many Requests", retry_after: int | None = None):
        super().__init__(429, message)
        self.retry_after = retry_after


