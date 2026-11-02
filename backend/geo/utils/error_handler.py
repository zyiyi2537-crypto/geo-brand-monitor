from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from jwt import PyJWTError as JWTError
from sqlalchemy.exc import SQLAlchemyError
import logging

from geo.utils.error_i18n import localize

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _request_lang(request: Request) -> str:
    """Best-effort language pick for outgoing error messages.

    Prefers an explicit `X-Locale` header (set by the frontend API clients)
    and falls back to the browser's `Accept-Language`. The value is passed
    verbatim to `localize()`, which handles normalization and unknown locales.
    """
    return (
        request.headers.get("x-locale")
        or request.headers.get("accept-language")
        or "en"
    )

# 统一错误响应模型
class ErrorResponse:
    def __init__(self, code: int, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details
    
    def dict(self):
        response = {
            "error": {
                "code": self.code,
                "message": self.message
            }
        }
        if self.details:
            response["error"]["details"] = self.details
        return response

# 自定义异常类
class AppException(Exception):
    def __init__(self, status_code: int, message: str, details: dict = None):
        self.status_code = status_code
        self.message = message
        self.details = details
        super().__init__(self.message)

# 全局异常处理
async def global_exception_handler(request: Request, exc: Exception):
    # 日志级别按异常类型区分:
    # - AppException / RequestValidationError / JWTError 是预期的业务/校验失败,
    #   info 记录即可,避免每次 402/429/401 都把整栈刷进日志引起误判。
    # - 其他一切都是真正的未知异常,err + exc_info 留给运维排障。
    if isinstance(exc, (AppException, RequestValidationError, JWTError)):
        logger.info(f"Handled business exception: {type(exc).__name__}: {exc}")
    else:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)

    lang = _request_lang(request)

    # 处理不同类型的异常
    if isinstance(exc, AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code=exc.status_code,
                message=localize(exc.message, lang),
                details=exc.details
            ).dict()
        )
    elif isinstance(exc, RequestValidationError):
        # 处理请求参数验证错误
        details = []
        for error in exc.errors():
            details.append({
                "field": error["loc"],
                "message": error["msg"],
                "type": error["type"]
            })
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=localize("Validation error", lang),
                details=details
            ).dict()
        )
    elif isinstance(exc, JWTError):
        # 处理 JWT 错误
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=ErrorResponse(
                code=status.HTTP_401_UNAUTHORIZED,
                message=localize("Invalid or expired token", lang)
            ).dict(),
            headers={"WWW-Authenticate": "Bearer"}
        )
    elif isinstance(exc, SQLAlchemyError):
        # 处理数据库错误
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=localize("Database error", lang)
            ).dict()
        )
    else:
        # 处理其他未预期的错误
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=localize("Internal server error", lang)
            ).dict()
        )
