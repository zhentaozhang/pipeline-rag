"""
统一响应格式 + camelCase 基类

从 router.py 抽出以解决 admin_auth ↔ router 循环导入问题。
"""

from typing import Any

from pydantic import BaseModel
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """所有响应 DTO 的基类，自动序列化字段名为 camelCase"""

    model_config = {"alias_generator": to_camel, "populate_by_name": True, "from_attributes": True}


class ApiResponse:
    """与前端约定的统一响应格式：{code, data, message}"""

    @staticmethod
    def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
        return {"code": 0, "data": data, "message": message}

    @staticmethod
    def fail(message: str = "error", code: int = -100) -> dict:
        return {"code": code, "data": None, "message": message}
