"""P1-5 稳定 chunk ID（内容派生）纯逻辑测试（无 DB / 无网络）。"""

from app.common.utils import stable_id_to_int
from app.config import get_settings
from app.document.chunker.utils import make_chunk_id


class TestDefaultSnowflake:
    def test_default_off_uses_snowflake(self):
        assert get_settings().chunk.stable_chunk_id_enabled is False
        cid = make_chunk_id("doc-1", "内容", 0, "child")
        assert cid.isdigit()

    def test_default_ids_unique(self):
        a = make_chunk_id("doc-1", "内容", 0, "child")
        b = make_chunk_id("doc-1", "内容", 0, "child")
        assert a != b


class TestStable:
    def test_deterministic_for_same_input(self, monkeypatch):
        monkeypatch.setattr(get_settings().chunk, "stable_chunk_id_enabled", True)
        a = make_chunk_id("doc-1", "内容X", 3, "child")
        b = make_chunk_id("doc-1", "内容X", 3, "child")
        assert a == b
        assert a.startswith("c") and len(a) == 25

    def test_varies_by_content(self, monkeypatch):
        monkeypatch.setattr(get_settings().chunk, "stable_chunk_id_enabled", True)
        assert make_chunk_id("doc-1", "甲", 0, "child") != make_chunk_id("doc-1", "乙", 0, "child")

    def test_varies_by_role(self, monkeypatch):
        # 本语料父块与子块内容相同（1:1），必须靠 role 区分避免 ID 冲突
        monkeypatch.setattr(get_settings().chunk, "stable_chunk_id_enabled", True)
        assert make_chunk_id("doc-1", "同内容", 0, "parent") != make_chunk_id(
            "doc-1", "同内容", 0, "child"
        )

    def test_varies_by_seq_and_doc(self, monkeypatch):
        monkeypatch.setattr(get_settings().chunk, "stable_chunk_id_enabled", True)
        base = make_chunk_id("doc-1", "同内容", 0, "child")
        assert base != make_chunk_id("doc-1", "同内容", 1, "child")
        assert base != make_chunk_id("doc-2", "同内容", 0, "child")

    def test_stable_id_to_int_deterministic(self, monkeypatch):
        monkeypatch.setattr(get_settings().chunk, "stable_chunk_id_enabled", True)
        cid = make_chunk_id("doc-1", "内容", 0, "child")
        assert stable_id_to_int(cid) == stable_id_to_int(cid)
        assert stable_id_to_int(cid) > 0
