"""
JEV 单 Pass 判别器核心实现
实现 Noul / Choice / Score 三大 System 1 原语，直接读取 Logits，避免自回归文本生成。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import torch
import torch.nn.functional as F

logger = logging.getLogger("jev_service.judger")

try:  # 兼容两种启动方式：仓库根目录 `python -m uvicorn jev_service.server:app` 与 jev_service/ 内启动
    from jev_service.prompt_budget import fit_state_to_budget
except ImportError:
    from prompt_budget import fit_state_to_budget


def _safe_encode_first_token(tokenizer, text: str) -> int:
    """提取文本编码后的首个前缀 Token ID（对应自回归生成的第一步目标 Token），未匹配返回 -1"""
    tokens = tokenizer.encode(text, add_special_tokens=False)
    if not tokens:
        return -1
    return tokens[0]


def _pool_token_logits(logits: torch.Tensor, token_ids: list[int]) -> torch.Tensor:
    """
    聚合候选 Token 列表的 Logit 质量。
    通过保留首次出现的保序去重 (dict.fromkeys)，彻底消除重复 Token ID 导致的 ln(2) 几率虚高偏差。
    """
    unique_ids = list(dict.fromkeys(tid for tid in token_ids if 0 <= tid < logits.shape[0]))
    if not unique_ids:
        return torch.tensor(-1e9, dtype=torch.float32)
    res = logits[unique_ids[0]]
    for uid in unique_ids[1:]:
        res = torch.logaddexp(res, logits[uid])
    return res


def _sanitize_chatml(text: str) -> str:
    """消除特殊控制字符注入，防止攻击者通过伪造 <|im_end|> 逃逸出用户上下文"""
    if not text:
        return ""
    return (
        text.replace("<|im_start|>", "[im_start]")
        .replace("<|im_end|>", "[im_end]")
        .replace("<|endoftext|>", "[endoftext]")
    )


class LocalJEVJudger:
    def __init__(self, model, tokenizer, device: str) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.device = device

        # 统一配置分词器为左填充与左截断（确保Prompt尾部的assistant标记绝不被裁剪）
        self.tokenizer.padding_side = "left"
        self.tokenizer.truncation_side = "left"

        # 缓存双语布尔 Token ID（中文是/否 + 英文大小写 Yes/No/True/False，统一去重并排除负数）
        raw_yes = [
            _safe_encode_first_token(self.tokenizer, "是"),
            _safe_encode_first_token(self.tokenizer, " 是"),
            _safe_encode_first_token(self.tokenizer, "Yes"),
            _safe_encode_first_token(self.tokenizer, " Yes"),
            _safe_encode_first_token(self.tokenizer, "yes"),
            _safe_encode_first_token(self.tokenizer, " yes"),
            _safe_encode_first_token(self.tokenizer, "True"),
            _safe_encode_first_token(self.tokenizer, " True"),
            _safe_encode_first_token(self.tokenizer, "true"),
            _safe_encode_first_token(self.tokenizer, " true"),
        ]
        raw_no = [
            _safe_encode_first_token(self.tokenizer, "否"),
            _safe_encode_first_token(self.tokenizer, " 否"),
            _safe_encode_first_token(self.tokenizer, "No"),
            _safe_encode_first_token(self.tokenizer, " No"),
            _safe_encode_first_token(self.tokenizer, "no"),
            _safe_encode_first_token(self.tokenizer, " no"),
            _safe_encode_first_token(self.tokenizer, "False"),
            _safe_encode_first_token(self.tokenizer, " False"),
            _safe_encode_first_token(self.tokenizer, "false"),
            _safe_encode_first_token(self.tokenizer, " false"),
        ]
        self.yes_token_ids = [tid for tid in raw_yes if tid >= 0]
        self.no_token_ids = [tid for tid in raw_no if tid >= 0]

        # 预先缓存 26 个大写字母及其小写与带空格变体 Token ID（用于多类别强单 Token 采样）
        self.labels = [chr(ord("A") + i) for i in range(26)]
        self.label_tokens = {}
        for ch in self.labels:
            t_upper = _safe_encode_first_token(self.tokenizer, ch)
            t_lower = _safe_encode_first_token(self.tokenizer, ch.lower())
            t_upper_sp = _safe_encode_first_token(self.tokenizer, f" {ch}")
            t_lower_sp = _safe_encode_first_token(self.tokenizer, f" {ch.lower()}")
            self.label_tokens[ch] = [
                tid for tid in [t_upper, t_lower, t_upper_sp, t_lower_sp] if tid >= 0
            ]

        # 单次前向可容纳的问题数（noul/choice/score 统一批处理）。过大会增加显存/内存峰值
        try:
            self._batch_chunk = max(1, int(os.getenv("JEV_BATCH_CHUNK", "8") or 8))
        except ValueError:
            self._batch_chunk = 8

        # Prompt 预算上限（token）：超限时截 state，绝不截判断标准/证据
        try:
            self._max_tokens = max(512, int(os.getenv("JEV_MAX_TOKENS", "4096") or 4096))
        except ValueError:
            self._max_tokens = 4096

    def _count_tokens(self, text: str) -> int:
        """真实分词长度（用于 Prompt 预算，不做任何截断）。"""
        if not text:
            return 0
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def _fit_state(self, state: str, build_prompt: Callable[[str], str]) -> str:
        """只截 state，保证判断标准 / 证据 / assistant 标记完整（见 prompt_budget 模块说明）。"""
        return fit_state_to_budget(
            state,
            count=self._count_tokens,
            build_prompt=build_prompt,
            max_tokens=self._max_tokens,
        )

    def _truncate_state(self, state: str, max_chars: int = 4000) -> str:
        """保护性截断待评估上下文，双端保留首尾核心信息，确保提示词长度平稳且不截断关键线索"""
        s = (state or "").strip()
        if len(s) > max_chars:
            head_len = int(max_chars * 0.7)
            tail_len = int(max_chars * 0.3)
            return f"{s[:head_len]}\n...[中间部分超长已截断]...\n{s[-tail_len:]}"
        return s

    def _build_noul_prompt(self, safe_state: str, instructions: str) -> str:
        safe_inst = _sanitize_chatml(instructions)
        return (
            f"<|im_start|>system\n"
            f"你是一个严谨的布尔判断器。根据待评估内容，严格判断是否符合标准。只需回答'是'或'否'，绝对不要输出任何其他字符。<|im_end|>\n"
            f"<|im_start|>user\n"
            f"判断标准：{safe_inst}\n\n"
            f"待评估内容：\n{safe_state}\n\n"
            f"结论（只输出'是'或'否'）：<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def _build_choice_prompt(
        self, safe_state: str, instructions: str, options: dict[str, str]
    ) -> str:
        safe_inst = _sanitize_chatml(instructions)
        opts_desc = "\n".join(
            f"{self.labels[i]}. {k}: {_sanitize_chatml(v)}"
            for i, (k, v) in enumerate(options.items())
            if i < len(self.labels)
        )
        return (
            f"<|im_start|>system\n"
            f"你是一个精准的分类判别器。严格根据待分类内容与选项描述做出互斥分类。只输出选项对应的单字母标签，绝对不要输出任何解释或多余字符。<|im_end|>\n"
            f"<|im_start|>user\n"
            f"分类标准：{safe_inst}\n\n"
            f"待分类内容：\n{safe_state}\n\n"
            f"候选选项：\n{opts_desc}\n\n"
            f"最佳选项标签（只输出单字母 A/B/C...）：<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def judge_noul(self, state: str, instructions: str) -> dict[str, Any]:
        """
        Noul 原语：输出真值判断结论与校准概率 [0.0, 1.0]
        """
        raw_state = _sanitize_chatml(state)
        safe_state = self._fit_state(raw_state, lambda s: self._build_noul_prompt(s, instructions))
        prompt = self._build_noul_prompt(safe_state, instructions)
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_tokens,
        ).to(self.device)

        t0 = time.perf_counter()
        with torch.no_grad():
            outputs = self.model(**inputs, use_cache=False)
            # 取最后一个位置的 logits 并转为 CPU FP32，保证后续数值运算稳定不溢出
            next_logits = outputs.logits[0, -1, :].to(dtype=torch.float32, device="cpu")
            del outputs, inputs

        # 聚合'是'和'否'的 token 几率质量（安全去重）
        logit_yes = _pool_token_logits(next_logits, self.yes_token_ids)
        logit_no = _pool_token_logits(next_logits, self.no_token_ids)

        pair_logits = torch.tensor([logit_yes.item(), logit_no.item()])
        probs = F.softmax(pair_logits, dim=-1)
        if torch.isnan(probs).any():
            probs = torch.tensor([0.5, 0.5])
        p_true = probs[0].item()
        p_false = probs[1].item()
        latency_ms = (time.perf_counter() - t0) * 1000

        return {
            "noul": round(p_true, 4),
            "is_true": p_true >= 0.5,
            "confidence": round(max(p_true, p_false), 4),
            "_latency_ms": round(latency_ms, 2),
        }

    def judge_choice(
        self, state: str, instructions: str, options: dict[str, str]
    ) -> dict[str, Any]:
        """
        Choice 原语：在互斥候选集 options 中进行单次选择，输出选中项与全分布
        采用标准 Letter-indexing (A., B., C....) 解决候选多 Token 前缀重叠问题
        """
        if not options:
            return {"choice": "", "confidence": 0.0, "distribution": {}}

        keys = list(options.keys())
        num_options = min(len(keys), len(self.labels))
        raw_state = _sanitize_chatml(state)
        safe_state = self._fit_state(
            raw_state, lambda s: self._build_choice_prompt(s, instructions, options)
        )
        prompt = self._build_choice_prompt(safe_state, instructions, options)
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_tokens,
        ).to(self.device)

        t0 = time.perf_counter()
        with torch.no_grad():
            outputs = self.model(**inputs, use_cache=False)
            next_logits = outputs.logits[0, -1, :].to(dtype=torch.float32, device="cpu")
            del outputs, inputs

        # 提取每个选项对应字母 [A, B, C...] 的 Logit，聚合大小写变体并安全去重
        cand_logits = []
        for i in range(num_options):
            lbl = self.labels[i]
            token_variants = self.label_tokens[lbl]
            cand_l = _pool_token_logits(next_logits, token_variants).item()
            cand_logits.append(cand_l)

        tensor_logits = torch.tensor(cand_logits, device="cpu")
        probs = F.softmax(tensor_logits, dim=-1)
        if torch.isnan(probs).any():
            probs = torch.full_like(tensor_logits, 1.0 / max(1, num_options))
        best_idx = int(probs.argmax().item())
        best_choice = keys[best_idx]
        confidence = probs[best_idx].item()
        latency_ms = (time.perf_counter() - t0) * 1000

        dist = {keys[i]: round(probs[i].item(), 4) for i in range(num_options)}

        return {
            "choice": best_choice,
            "confidence": round(confidence, 4),
            "distribution": dist,
            "_latency_ms": round(latency_ms, 2),
        }

    def _score_noul_row(self, next_logits: torch.Tensor) -> dict[str, Any]:
        """对单个(行)末位 logits 计算 Noul 结论（供批量复用）。"""
        logit_yes = _pool_token_logits(next_logits, self.yes_token_ids)
        logit_no = _pool_token_logits(next_logits, self.no_token_ids)
        pair = torch.tensor([logit_yes.item(), logit_no.item()])
        probs = F.softmax(pair, dim=-1)
        if torch.isnan(probs).any():
            probs = torch.tensor([0.5, 0.5])
        p_true = probs[0].item()
        p_false = probs[1].item()
        return {
            "noul": round(p_true, 4),
            "is_true": p_true >= 0.5,
            "confidence": round(max(p_true, p_false), 4),
        }

    def _score_choice_row(self, next_logits: torch.Tensor, keys: list[str]) -> dict[str, Any]:
        """对单个(行)末位 logits 计算 Choice 结论（供批量复用）。"""
        num_options = min(len(keys), len(self.labels))
        cand_logits = []
        for i in range(num_options):
            token_variants = self.label_tokens[self.labels[i]]
            cand_logits.append(_pool_token_logits(next_logits, token_variants).item())
        tensor_logits = torch.tensor(cand_logits)
        probs = F.softmax(tensor_logits, dim=-1)
        if torch.isnan(probs).any():
            probs = torch.full_like(tensor_logits, 1.0 / max(1, num_options))
        best_idx = int(probs.argmax().item())
        return {
            "choice": keys[best_idx],
            "confidence": round(probs[best_idx].item(), 4),
            "distribution": {keys[i]: round(probs[i].item(), 4) for i in range(num_options)},
        }

    def judge_noul_batch(
        self, state: str, items: list[tuple[str, str]]
    ) -> dict[str, dict[str, Any]]:
        """
        高通量批量 Noul 判别：通过左填充 (left-padding) 在模型前向中并行评测全部布尔命题
        采用分块批处理 (max chunk size=4) 防御极端大请求下的 GPU/CPU 显存突增 (OOM)
        """
        if not items:
            return {}
        if len(items) == 1:
            q_name, q_inst = items[0]
            return {q_name: self.judge_noul(state, q_inst)}

        raw_state = _sanitize_chatml(state)
        self.tokenizer.padding_side = "left"
        results = {}
        chunk_size = 4
        for chunk_idx in range(0, len(items), chunk_size):
            chunk_items = items[chunk_idx : chunk_idx + chunk_size]
            prompts = [
                self._build_noul_prompt(
                    self._fit_state(raw_state, lambda s, i=q_inst: self._build_noul_prompt(s, i)),
                    q_inst,
                )
                for _, q_inst in chunk_items
            ]
            inputs = self.tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self._max_tokens,
            ).to(self.device)

            t0 = time.perf_counter()
            with torch.no_grad():
                outputs = self.model(**inputs, use_cache=False)
                # 左填充保证每行的 [-1] 均为目标 prompt 的结尾位置
                batch_logits = outputs.logits[:, -1, :].to(dtype=torch.float32, device="cpu")
                del outputs, inputs

            latency_ms = (time.perf_counter() - t0) * 1000
            avg_latency = round(latency_ms / len(chunk_items), 2)
            for idx, (q_name, _) in enumerate(chunk_items):
                next_logits = batch_logits[idx]
                logit_yes = _pool_token_logits(next_logits, self.yes_token_ids)
                logit_no = _pool_token_logits(next_logits, self.no_token_ids)

                pair_logits = torch.tensor([logit_yes.item(), logit_no.item()])
                probs = F.softmax(pair_logits, dim=-1)
                if torch.isnan(probs).any():
                    probs = torch.tensor([0.5, 0.5])
                p_true = probs[0].item()
                p_false = probs[1].item()

                results[q_name] = {
                    "noul": round(p_true, 4),
                    "is_true": p_true >= 0.5,
                    "confidence": round(max(p_true, p_false), 4),
                    "_latency_ms": avg_latency,
                }
        return results

    def judge_score(self, state: str, instructions: str, levels: list[str]) -> dict[str, Any]:
        """
        Score 原语：基于等级列表对状态进行评级打分
        """
        if not levels:
            return {"score": "", "confidence": 0.0, "distribution": {}}

        options = {lv: f"判定为【{lv}】等级" for lv in levels}
        choice_res = self.judge_choice(state, instructions, options)
        return {
            "score": choice_res["choice"],
            "confidence": choice_res["confidence"],
            "distribution": choice_res["distribution"],
            "_latency_ms": choice_res.get("_latency_ms", 0.0),
        }

    def _forward_last_logits(self, inputs: Any) -> torch.Tensor:
        """只取每个序列末位的 logits。

        优化：若模型暴露 transformer 主体 + lm_head，则仅对**最后位置**应用 lm_head，
        避免对整个序列长度做 vocab 维度投影（对分类式判定无意义且耗时）。
        """
        with torch.inference_mode():
            base = getattr(self.model, "model", None)
            lm_head = None
            if hasattr(self.model, "get_output_embeddings"):
                try:
                    lm_head = self.model.get_output_embeddings()
                except Exception:
                    lm_head = None
            if base is not None and base is not self.model and lm_head is not None:
                out = base(**inputs, use_cache=False)
                hidden = out.last_hidden_state[:, -1, :]
                logits = lm_head(hidden)
            else:
                out = self.model(**inputs, use_cache=False)
                logits = out.logits[:, -1, :]
            return logits.to(dtype=torch.float32, device="cpu")

    def judge_batch(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        """
        批量计算请求中的全部决策问题。

        关键优化：把同一请求内的所有 Noul / Choice / Score 问题统一左填充为一个
        批次，仅做**一次模型前向**，再逐行抽取对应 logits —— 相比"每个问题各跑一次
        前向"，N 个问题的耗时由 O(N) 降为 O(1) 次前向。
        """
        entries, answers = self._build_entries(state, questions)
        scored = self._score_flat(entries)
        for (q_name, *_rest), res in zip(entries, scored, strict=False):
            answers[q_name] = res
        return answers

    def judge_entries_multi(self, batch: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        """跨请求批量推理：把多个 (state, questions) 展开成行，一次前向后按请求切回。

        这是解决"并发被全局锁串行化"的关键：多个 HTTP 请求可以在**同一次**前向里
        完成，而不是排队。单次合并的行数由 JEV_BATCH_MAX_ROWS 控制。
        """
        if not batch:
            return []
        per_request: list[tuple[list[tuple], dict[str, Any]]] = [
            self._build_entries(state, questions) for state, questions in batch
        ]
        flat: list[tuple] = [entry for entries, _ in per_request for entry in entries]
        scored = self._score_flat(flat)

        out: list[dict[str, Any]] = []
        cursor = 0
        for entries, answers in per_request:
            merged = dict(answers)
            for (q_name, *_rest), res in zip(
                entries, scored[cursor : cursor + len(entries)], strict=False
            ):
                merged[q_name] = res
            cursor += len(entries)
            out.append(merged)
        return out

    def _build_entries(
        self, state: str, questions: dict[str, Any]
    ) -> tuple[list[tuple], dict[str, Any]]:
        """把 questions 展开成 (q_name, kind, prompt, keys) 行；非法项直接落答案。"""
        if not questions:
            return [], {}

        raw_state = _sanitize_chatml(state)
        self.tokenizer.padding_side = "left"

        # 构建每个问题的 prompt 与其候选键（同一批次共享一次前向）
        entries: list[tuple[str, str, str | None, list[str] | None]] = []
        answers: dict[str, Any] = {}
        for q_name, q_item in questions.items():
            if not q_item:
                continue
            q_type = getattr(q_item, "type", None) or (
                q_item.get("type") if isinstance(q_item, dict) else None
            )
            q_inst = (
                getattr(q_item, "instructions", None)
                or (q_item.get("instructions") if isinstance(q_item, dict) else "")
                or ""
            )
            if q_type == "noul":
                inst = str(q_inst)
                fitted = self._fit_state(raw_state, lambda s, i=inst: self._build_noul_prompt(s, i))
                entries.append((q_name, "noul", self._build_noul_prompt(fitted, inst), None))
            elif q_type == "choice":
                opts = (
                    getattr(q_item, "options", None)
                    or (q_item.get("options") if isinstance(q_item, dict) else {})
                    or {}
                )
                if not opts:
                    answers[q_name] = {"choice": "", "confidence": 0.0, "distribution": {}}
                    continue
                keys = list(opts.keys())[: len(self.labels)]
                inst = str(q_inst)
                fitted = self._fit_state(
                    raw_state, lambda s, i=inst, o=opts: self._build_choice_prompt(s, i, o)
                )
                entries.append(
                    (q_name, "choice", self._build_choice_prompt(fitted, inst, opts), keys)
                )
            elif q_type == "score":
                levels = (
                    getattr(q_item, "levels", None)
                    or (q_item.get("levels") if isinstance(q_item, dict) else [])
                    or []
                )
                if not levels:
                    answers[q_name] = {"score": "", "confidence": 0.0, "distribution": {}}
                    continue
                options = {lv: f"判定为【{lv}】等级" for lv in levels}
                keys = list(options.keys())[: len(self.labels)]
                inst = str(q_inst)
                fitted = self._fit_state(
                    raw_state, lambda s, i=inst, o=options: self._build_choice_prompt(s, i, o)
                )
                entries.append(
                    (q_name, "score", self._build_choice_prompt(fitted, inst, options), keys)
                )
            else:
                logger.warning("Unsupported JEV primitive type: %s", q_type)

        return entries, answers

    def _score_flat(self, entries: list[tuple]) -> list[dict[str, Any]]:
        """对展开后的行做分批前向，返回与输入等长的结果列表。"""
        results: list[dict[str, Any]] = []
        for start in range(0, len(entries), self._batch_chunk):
            group = entries[start : start + self._batch_chunk]
            prompts = [e[2] for e in group]
            inputs = self.tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self._max_tokens,
            ).to(self.device)

            t0 = time.perf_counter()
            # 左填充保证每行的 [-1] 均为 prompt 结尾位置
            batch_logits = self._forward_last_logits(inputs)
            del inputs
            latency_ms = (time.perf_counter() - t0) * 1000
            per_question_ms = round(latency_ms / len(group), 2)

            for idx, (_q_name, kind, _prompt, keys) in enumerate(group):
                next_logits = batch_logits[idx]
                if kind == "noul":
                    res = self._score_noul_row(next_logits)
                else:
                    choice_res = self._score_choice_row(next_logits, keys or [])
                    if kind == "score":
                        res = {
                            "score": choice_res["choice"],
                            "confidence": choice_res["confidence"],
                            "distribution": choice_res["distribution"],
                        }
                    else:
                        res = choice_res
                res["_latency_ms"] = per_question_ms
                results.append(res)
        return results
