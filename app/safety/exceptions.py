"""
安全检测层异常 + 错误码
"""

from app.common.exceptions import PipelineRAGBaseException


class CircuitBreakerException(PipelineRAGBaseException):
    """熔断器异常——服务暂时不可用"""

    pass
