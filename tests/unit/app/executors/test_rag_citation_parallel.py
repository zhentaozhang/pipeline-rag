"""P1-c：引用校验与质量自审并发预跑（纯内存，无 DB/LLM）。"""

import app.executors.rag as rag_mod
from app.chat.task_info import ChatTaskInfo
from app.executors.rag import RagChatExecutor


def _make_task(with_refs: bool = True) -> ChatTaskInfo:
    task = ChatTaskInfo(conversation_id="c1", question="q")
    if with_refs:
        task.references.append({"id": "r1", "title": "T", "content": "证据"})
    return task


def _patch_llm(monkeypatch, calls: list[str], enabled: bool = True) -> None:
    async def _fake_verify(*, fallback, answer, references, question=""):
        calls.append(answer)
        return answer, [], {"status": "judged"}

    monkeypatch.setattr(rag_mod, "verify_citations", _fake_verify)
    monkeypatch.setattr(rag_mod, "citation_verify_enabled", lambda: enabled)
    monkeypatch.setattr("app.common.llm_client.get_chat_client", lambda: object())
    monkeypatch.setattr("app.infra.model_fallback.ModelFallbackManager", lambda client: object())


async def test_starts_and_awaits(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls)
    task = _make_task()

    RagChatExecutor(db=None, task=task)._start_citation_task("回答内容 [1]", "问题")

    assert task._citation_task is not None
    base, _verified, bad_refs, meta = await task._citation_task
    assert base == "回答内容 [1]"
    assert bad_refs == []
    assert meta["status"] == "judged"
    assert calls == ["回答内容 [1]"]


async def test_skip_without_citation(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls)
    task = _make_task()

    RagChatExecutor(db=None, task=task)._start_citation_task("没有引用的回答", "问题")

    assert task._citation_task is None
    assert calls == []


async def test_skip_without_references(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls)
    task = _make_task(with_refs=False)

    RagChatExecutor(db=None, task=task)._start_citation_task("回答 [1]", "问题")

    assert task._citation_task is None
    assert calls == []


async def test_skip_when_verifier_disabled(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls, enabled=False)
    task = _make_task()

    RagChatExecutor(db=None, task=task)._start_citation_task("回答 [1]", "问题")

    assert task._citation_task is None
    assert calls == []


async def test_skip_when_parallel_disabled(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls)
    monkeypatch.setattr(rag_mod.settings.rag, "citation_verify_parallel_enabled", False)
    task = _make_task()

    RagChatExecutor(db=None, task=task)._start_citation_task("回答 [1]", "问题")

    assert task._citation_task is None
    assert calls == []


async def test_skip_in_worker_execution(monkeypatch):
    calls: list[str] = []
    _patch_llm(monkeypatch, calls)
    task = _make_task()
    executor = RagChatExecutor(db=None, task=task)
    executor._worker_execution = True

    executor._start_citation_task("回答 [1]", "问题")

    assert task._citation_task is None
    assert calls == []
