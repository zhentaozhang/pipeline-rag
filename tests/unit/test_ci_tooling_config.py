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


# ── 门禁"永不触发"与依赖漂移的回归守卫（2026-10-24）─────────────────────────
SETUP_UV = "astral-sh/setup-uv@"
JEV_REQUIREMENTS = REPO_ROOT / "jev_service" / "requirements.txt"
JEV_LOCK = REPO_ROOT / "jev_service" / "requirements.lock.txt"

_SETUP_UV_VERSION = re.compile(
    r"uses:\s*"
    + re.escape(SETUP_UV)
    + r"\S+\s*\n\s*with:\s*\n(?:\s*#.*\n)*\s*version:\s*\"([^\"]+)\""
)
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def test_setup_uv_pins_concrete_version() -> None:
    """CI 安装 uv 必须钉死版本：`latest` 会让某个早上 uv 升级就改变 CI 行为而仓库无 diff。"""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    versions = _SETUP_UV_VERSION.findall(workflow)
    assert versions, "ci.yml 里没有解析到 setup-uv 的 version"
    assert all(v.lower() != "latest" for v in versions), (
        f"setup-uv 不能使用 latest：{versions}。"
        "锁解析器版本漂移会让 uv.lock 的解析结果在不同时间不一致。"
    )


def test_decision_ab_gate_is_not_permanently_skipped() -> None:
    """decision-ab 不能在只依赖仓库变量时被永久跳过（那等于"界面绿但零覆盖"）。"""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    start = workflow.find("  decision-ab:")
    assert start > 0, "ci.yml 里找不到 decision-ab job"
    body = workflow[start : start + 1200]
    condition_start = body.find("if:")
    condition_end = body.find("runs-on:")
    assert 0 <= condition_start < condition_end, "decision-ab 缺少 if: 条件"
    condition = body[condition_start:condition_end]
    assert "github.event_name == 'schedule'" in condition, (
        "decision-ab 必须能在夜间 schedule 上真实运行，否则 JEV 质量门禁形同不存在；"
        f"当前条件：{condition.strip()}"
    )
    assert "--require-jev" in workflow, "JEV 门禁必须带 --require-jev，服务不可达时要失败而不是跳过"


def test_jev_requirements_lock_covers_every_top_level_requirement() -> None:
    """jev_service 依赖必须有冻结锁，且锁里覆盖 requirements.txt 的每个顶层依赖。"""
    assert JEV_LOCK.exists(), (
        "缺少 jev_service/requirements.lock.txt，Dockerfile 将失去可复现的依赖集"
    )
    lock_text = JEV_LOCK.read_text(encoding="utf-8")
    pinned = {
        line.split("==", 1)[0].strip().lower()
        for line in lock_text.splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    }
    top_level = []
    for line in JEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = _REQ_NAME.match(stripped)
        if match:
            top_level.append(match.group(1).lower())
    assert top_level, "jev_service/requirements.txt 里没有解析到依赖"
    missing = [name for name in top_level if name not in pinned]
    assert not missing, f"这些依赖没被锁住（改完 requirements.txt 要跑 make jev-lock）：{missing}"


def test_jev_dockerfile_installs_from_lock_not_bare_requirements() -> None:
    """Dockerfile 必须安装冻结锁，否则 `>=` 约束会在构建时静默漂移。"""
    dockerfile = (REPO_ROOT / "jev_service" / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements.lock.txt" in dockerfile, (
        "jev_service/Dockerfile 没有使用 requirements.lock.txt"
    )
    assert "pip install --no-cache-dir -r requirements.lock.txt" in dockerfile


# ── 多分类门禁必须同时卡准确率与宏 F1（2026-10-24）───────────────────────────
MAKEFILE = REPO_ROOT / "Makefile"


def test_decision_ab_gate_passes_multi_class_thresholds() -> None:
    """门禁命令必须真的传 --min-accuracy / --min-macro-f1。

    只写 flag 不传值等于没门禁：2026-10-24 之前 --min-accuracy 全仓库无人传，
    多分类的宏 F1 退化（structure_ambiguity 0.794）一路放行。
    """
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    start = workflow.find("name: Decision A/B gate (JEV)")
    assert start > 0, "ci.yml 里找不到 Decision A/B gate 步骤"
    command = workflow[start : workflow.find("- name:", start + 10)]
    for flag in ("--min-accuracy", "--min-macro-f1", "--min-recall", "--require-jev"):
        assert flag in command, f"decision-ab 门禁命令缺少 {flag}"
    for flag in ("--min-accuracy", "--min-macro-f1"):
        value = re.search(re.escape(flag) + r"\s+([0-9.]+)", command)
        assert value is not None, f"{flag} 没有传具体阈值，等于关闭该门禁"
        assert float(value.group(1)) > 0.0, f"{flag} 阈值必须大于 0，否则门禁永不触发"


def test_makefile_eval_ab_uses_same_thresholds_as_ci() -> None:
    """make eval-ab 与 CI 的门禁必须同源，否则本地绿/CI 红会再次分叉。"""
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    ci_start = workflow.find("name: Decision A/B gate (JEV)")
    ci_command = workflow[ci_start : workflow.find("- name:", ci_start + 10)]
    makefile = MAKEFILE.read_text(encoding="utf-8")
    make_start = makefile.find("eval-ab:")
    assert make_start > 0, "Makefile 里找不到 eval-ab 目标"
    make_command = makefile[make_start : makefile.find("\n\n", make_start)]
    for flag in ("--min-recall", "--min-precision", "--min-f1", "--min-accuracy", "--min-macro-f1"):
        ci_value = re.search(re.escape(flag) + r"\s+([0-9.]+)", ci_command)
        make_value = re.search(re.escape(flag) + r"\s+([0-9.]+)", make_command)
        assert make_value is not None, f"make eval-ab 缺少 {flag}"
        assert ci_value is not None, f"CI 门禁缺少 {flag}"
        assert ci_value.group(1) == make_value.group(1), (
            f"{flag} 阈值不一致：CI={ci_value.group(1)}，make={make_value.group(1)}"
        )
