"""工具链 pin 一致性：pre-commit 与 CI 必须用同一个 ruff，且格式门禁不被前置失败掩盖。

背景：2026-10-23 的 CI 失败是 ruff format（12 个文件未格式化）。本地 pre-commit 当时是
绿的，因为 .pre-commit-config.yaml 的 rev 停在 v0.5.0，而 uv.lock 已经是 0.15.22——同一个
工具被两处独立 pin，必然再次漂移。另外 format 步骤排在 mypy/单测之前，导致纯风格失败把
5 个 mypy 错误掩盖了 6 天。这两个不变量在这里用断言固化，任何一侧被改歪 CI 立刻红。
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
UV_LOCK = REPO_ROOT / "uv.lock"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

RUFF_PRE_COMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"

_REPO_ENTRY = re.compile(r"^\s*- repo:\s*(\S+)\s*$", re.MULTILINE)
_REV = re.compile(r"^\s*rev:\s*v?(\S+)\s*$", re.MULTILINE)
_HOOK_ID = re.compile(r"^\s*- id:\s*(\S+)\s*$", re.MULTILINE)


def _pre_commit_repo_block(repo: str) -> str:
    """取出某个 repo 段（到下一个 `- repo:` 或文件末尾），避免误读别的 hook。"""
    text = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
    entries = list(_REPO_ENTRY.finditer(text))
    for index, entry in enumerate(entries):
        if entry.group(1).rstrip("/") != repo.rstrip("/"):
            continue
        end = entries[index + 1].start() if index + 1 < len(entries) else len(text)
        return text[entry.start() : end]
    raise AssertionError(f"{PRE_COMMIT_CONFIG.name} 里找不到 repo: {repo}")


def _locked_ruff_version() -> str:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    for package in lock.get("package", []):
        if package.get("name") == "ruff":
            return str(package["version"])
    raise AssertionError("uv.lock 里没有 ruff，请检查 ruff 是否仍在 dev 依赖中")


def test_pre_commit_ruff_rev_matches_locked_ruff() -> None:
    """pre-commit 的 ruff rev 必须等于 uv.lock 锁定的 ruff 版本。"""
    block = _pre_commit_repo_block(RUFF_PRE_COMMIT_REPO)
    rev = _REV.search(block)
    assert rev is not None, "ruff-pre-commit 段缺少 rev"
    assert rev.group(1) == _locked_ruff_version(), (
        "pre-commit 的 ruff rev 与 uv.lock 不一致："
        f"pre-commit={rev.group(1)}，uv.lock={_locked_ruff_version()}。"
        "两处 pin 漂移会让本地检查与 CI 判定分叉。"
    )


def test_ruff_hooks_use_non_legacy_ids() -> None:
    """`ruff` 已是 legacy alias，统一用 ruff-check / ruff-format。"""
    block = _pre_commit_repo_block(RUFF_PRE_COMMIT_REPO)
    assert _HOOK_ID.findall(block) == ["ruff-check", "ruff-format"]


def test_format_gate_runs_after_substantive_checks() -> None:
    """CI 里 Format check 必须排在 Unit tests 之后，避免风格失败掩盖 mypy/单测失败。"""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    format_index = workflow.find("name: Format check (ruff)")
    unit_tests_index = workflow.find("name: Unit tests")
    mypy_index = workflow.find("name: Type check (mypy)")
    assert format_index > 0, "ci.yml 里找不到 Format check 步骤"
    assert unit_tests_index > 0, "ci.yml 里找不到 Unit tests 步骤"
    assert mypy_index > 0, "ci.yml 里找不到 Type check 步骤"
    assert format_index > unit_tests_index > mypy_index, (
        "格式门禁必须排在 mypy/单测之后：纯风格失败不应让实质检查被跳过"
    )
