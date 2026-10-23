"""
JEV 基础模型加载器与单例管理器
"""

import logging
import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger("jev_service.model_loader")

_tokenizer = None
_model = None
_device = None


def get_device() -> str:
    global _device
    if _device is not None:
        return _device
    env_dev = os.getenv("JEV_DEVICE", "").strip().lower()
    if env_dev in ("cpu", "cuda", "mps"):
        _device = env_dev
    elif torch.cuda.is_available():
        _device = "cuda"
    elif torch.backends.mps.is_available():
        _device = "mps"
    else:
        _device = "cpu"
    logger.info("JEV service running on device: %s", _device)
    return _device


def _ensure_cache_dir() -> str | None:
    """
    检查缓存目录写权限（特别防御 Docker 挂载数据卷为 root 用户导致非 root appuser 写入 PermissionError）
    """
    hf_home = os.getenv("HF_HOME") or "/data/cache"
    try:
        os.makedirs(hf_home, exist_ok=True)
        test_file = os.path.join(hf_home, ".perm_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return hf_home
    except (OSError, PermissionError) as exc:
        fallback = os.path.expanduser("~/.cache/huggingface")
        logger.warning(
            "Cache directory '%s' is not writable (%s). Falling back to user cache '%s'.",
            hf_home,
            exc,
            fallback,
        )
        try:
            os.makedirs(fallback, exist_ok=True)
            os.environ["HF_HOME"] = fallback
            return fallback
        except Exception as e:
            logger.error("Failed to initialize fallback cache directory: %s", e)
            return None


def get_model_and_tokenizer():
    global _model, _tokenizer
    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer

    _ensure_cache_dir()

    hf_endpoint = os.getenv("HF_ENDPOINT", "").strip()
    if hf_endpoint:
        os.environ["HF_ENDPOINT"] = hf_endpoint

    model_name = os.getenv("JEV_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    device = get_device()
    logger.info("Loading JEV base model: %s on %s...", model_name, device)

    _tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )
    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token

    dtype = torch.bfloat16
    if device == "cuda":
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    elif device == "mps":
        dtype = torch.float16

    _model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=dtype,
        device_map=None,
        trust_remote_code=True,
    )
    if _model.config.pad_token_id is None and _tokenizer.pad_token_id is not None:
        _model.config.pad_token_id = _tokenizer.pad_token_id
    for p in _model.parameters():
        p.requires_grad = False
    _model.to(device)
    _model.eval()
    logger.info("JEV base model loaded successfully.")
    return _model, _tokenizer
