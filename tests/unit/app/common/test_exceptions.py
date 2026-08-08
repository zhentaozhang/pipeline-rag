import pytest

from app.common.exceptions import (
    ArgumentException,
    AuthException,
    BaseCode,
    PipelineRAGBaseException,
    PipelineRAGFrameException,
    RateLimitException,
)


class TestBaseCode:
    def test_values(self):
        assert BaseCode.BAD_REQUEST == 10054
        assert BaseCode.UNAUTHORIZED == 401
        assert BaseCode.FORBIDDEN == 403
        assert BaseCode.NOT_FOUND == 404
        assert BaseCode.SYSTEM_ERROR == -1


class TestExceptions:
    def test_base_hierarchy(self):
        exc = PipelineRAGBaseException(10054, "msg")
        assert exc.code == 10054
        assert exc.message == "msg"
        assert str(exc) == "msg"
        assert isinstance(PipelineRAGFrameException(1, "m"), PipelineRAGBaseException)

    def test_argument_exception(self):
        exc = ArgumentException("参数错误", [{"field": "question", "error": "必填"}])
        assert exc.code == BaseCode.BAD_REQUEST
        assert exc.errors == [{"field": "question", "error": "必填"}]

    def test_argument_exception_default_errors(self):
        exc = ArgumentException("参数错误")
        assert exc.errors == []

    def test_auth_exception(self):
        exc = AuthException()
        assert exc.code == BaseCode.UNAUTHORIZED
        assert exc.message == "Unauthorized"
        assert isinstance(exc, PipelineRAGBaseException)

    def test_rate_limit_exception(self):
        exc = RateLimitException(retry_after=5)
        assert exc.code == 429
        assert exc.retry_after == 5
        assert "Too Many Requests" in exc.message

    def test_rate_limit_default(self):
        exc = RateLimitException()
        assert exc.retry_after is None

    def test_raise_catch(self):
        with pytest.raises(PipelineRAGBaseException) as excinfo:
            raise ArgumentException("校验失败")
        assert excinfo.value.code == 10054
