"""DocumentStructureAmbiguityResolver 的 JEV 路径单测（mock JEV）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document.structure.ambiguity import DocumentStructureAmbiguityResolver
from app.document.structure.models import (
    DocumentStructureSignal,
    DocumentStructureSignalKind,
)


def _signal(line_no: int) -> DocumentStructureSignal:
    return DocumentStructureSignal(
        line_no=line_no,
        raw_text=f"line {line_no}",
        normalized_text=f"line {line_no}",
        kind=DocumentStructureSignalKind.HEADING_CANDIDATE,
        confidence=0.6,
    )


def _patch_jev(answers: dict):
    mock = MagicMock()
    mock.system_one = AsyncMock(return_value=answers)
    return patch("app.infra.jev_client.get_jev_client", return_value=mock)


@pytest.mark.asyncio
async def test_resolve_via_jev_applies_kind_and_level():
    resolver = DocumentStructureAmbiguityResolver()
    signals = [_signal(3), _signal(7)]
    answers = {
        "kind_3": {"choice": "heading", "confidence": 0.9},
        "level_3": {"score": "二级标题", "confidence": 0.8},
        "kind_7": {"choice": "body", "confidence": 0.9},
        "level_7": {"score": "一级标题", "confidence": 0.8},
    }
    with _patch_jev(answers):
        merged = await resolver._resolve_via_jev(
            ["a", "b", "c", "d", "e", "f", "g"], signals, signals
        )

    assert merged[0].kind == DocumentStructureSignalKind.HEADING
    assert merged[0].level_hint == 2
    assert merged[1].kind == DocumentStructureSignalKind.BODY
    assert merged[1].level_hint is None


@pytest.mark.asyncio
async def test_resolve_via_jev_missing_kind_raises():
    resolver = DocumentStructureAmbiguityResolver()
    signals = [_signal(3)]
    with _patch_jev({"level_3": {"score": "一级标题"}}), pytest.raises(ValueError):
        await resolver._resolve_via_jev(["a", "b", "c"], signals, signals)


@pytest.mark.asyncio
async def test_resolve_via_jev_empty_raises_for_fallback():
    resolver = DocumentStructureAmbiguityResolver()
    signals = [_signal(3)]
    with _patch_jev({}), pytest.raises(ValueError):
        await resolver._resolve_via_jev(["a", "b", "c"], signals, signals)
