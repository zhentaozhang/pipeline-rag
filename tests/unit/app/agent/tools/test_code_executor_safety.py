"""C3 安全修复（TDD）：code_executor 逃逸与资源耗尽防护。

RED 阶段锁定两个已验证漏洞：
1. 属性链逃逸取得 Popen / 读文件（RCE）
2. 死循环超时后线程不停止
"""


async def test_mro_escape_is_rejected():
    """`().__class__.__base__.__subclasses__()` 属性链逃逸必须被拦截。"""
    from app.agent.tools.code_executor import code_executor

    payload = (
        "print([c.__name__ for c in ()"
        ".__class__.__base__.__subclasses__() if 'Popen' in c.__name__])"
    )
    result = await code_executor.ainvoke({"code": payload, "timeout": 3})
    assert "Popen" not in result, f"逃逸未拦截，实际返回: {result[:120]}"


async def test_direct_attribute_escape_is_rejected():
    """通过 __bases__ / __mro__ / __subclasses__ 访问内部对象链必须被拦截。"""
    from app.agent.tools.code_executor import code_executor

    for attr in ("__bases__", "__mro__", "__globals__", "__builtins__"):
        payload = f"print((1).__class__.{attr})"
        result = await code_executor.ainvoke({"code": payload, "timeout": 3})
        assert "<" not in result and "Popen" not in result, f"{attr} 泄露: {result[:80]}"


async def test_infinite_loop_times_out_cleanly():
    """死循环必须被超时终止，返回超时信息而非卡死。"""
    from app.agent.tools.code_executor import code_executor

    result = await code_executor.ainvoke({"code": "while True: pass", "timeout": 1})
    assert "超时" in result