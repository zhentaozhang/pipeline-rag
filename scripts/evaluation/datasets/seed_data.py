"""
种子测试集 — 基于真实文档（FastMCP 用户手册 + FastAPI 学习笔记）

数据来源：
- demo_docs/fastmcp_docs/   — FastMCP 框架官方文档（104 个 Markdown 文件，7 个章节）
- demo_docs/fastapi_notes.md — FastAPI 个人学习笔记（1746 行）

每条测试数据对应一个可以用文档内容回答的自然语言问题。
"""

from scripts.evaluation.datasets.base import EvalQuestion

SEED_DATASET: list[EvalQuestion] = [
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 快速入门
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev001",
        question="如何创建一个最简单的 FastMCP 服务器？",
        ground_truth_answer=(
            "创建一个 .py 文件，实例化 FastMCP 类，然后调用 run() 方法。\n"
            "示例：\n"
            "from fastmcp import FastMCP\n\n"
            'mcp = FastMCP("My MCP Server")\n\n'
            'if __name__ == "__main__":\n'
            "    mcp.run()\n\n"
            "默认使用 stdio 传输方式。也可以指定 transport='http' 实现 HTTP 传输。"
        ),
        relevant_contexts=[
            'from fastmcp import FastMCP\n\nmcp = FastMCP("My MCP Server")',
            'if __name__ == "__main__":\n    mcp.run()',
            'mcp.run(transport="http", port=8000)',
        ],
        relevant_document_ids=["doc_fastmcp_getting_started"],
        metadata={"category": "usage", "difficulty": "easy"},
    ),
    EvalQuestion(
        id="ev002",
        question="FastMCP CLI 怎么运行一个服务器？",
        ground_truth_answer=(
            "使用 fastmcp run 命令，格式为 fastmcp run <文件路径>:<服务器变量名>。\n"
            "示例：\n"
            "  fastmcp run my_server.py:mcp  （stdio 传输，默认）\n"
            "  fastmcp run my_server.py:mcp --transport http --port 8000（HTTP 传输）\n\n"
            "注意：CLI 不会执行服务器文件的 __main__ 块，而是直接导入服务器对象。"
        ),
        relevant_contexts=[
            "fastmcp run my_server.py:mcp",
            "fastmcp run my_server.py:mcp --transport http --port 8000",
            "FastMCP CLI **不会**执行服务器文件的 `__main__` 块。它会导入您的服务器对象并使用您提供的传输方式和选项运行它。",
        ],
        relevant_document_ids=["doc_fastmcp_getting_started"],
        metadata={"category": "usage", "difficulty": "easy"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 工具（核心概念）
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev003",
        question="FastMCP 的 @mcp.tool 装饰器支持哪些参数来覆盖工具元数据？",
        ground_truth_answer=(
            "@mcp.tool 装饰器支持以下参数来覆盖工具元数据：\n"
            "- name：自定义工具名称\n"
            "- description：自定义描述（设置后将忽略函数文档字符串）\n"
            "- tags：用于分类的字符串集合\n"
            "- enabled：布尔值（v3.0.0 已弃用，改用 mcp.enable()/disable()）\n"
            "- icons：可选图标表示列表\n"
            "- annotations：ToolAnnotations 对象，添加额外元数据\n"
            "- meta：可选元信息字典\n"
            "- timeout：执行超时（秒）\n"
            "- version：可选的版本标识符\n"
            "- output_schema：工具输出的可选 JSON 模式"
        ),
        relevant_contexts=[
            "@mcp.tool(\n"
            '    name="find_products",           # 自定义工具名称\n'
            '    description="搜索产品目录并进行可选的类别过滤。", # 自定义描述\n'
            '    tags={"catalog", "search"},      # 用于组织/过滤的可选标签\n'
            '    meta={"version": "1.2", "author": "product-team"}  # 自定义元数据\n'
            ")",
            "「name」、「description」、「tags」、「enabled」、「icons」、「annotations」、「meta」、「timeout」、「version」、「output_schema」",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    EvalQuestion(
        id="ev004",
        question="FastMCP 工具如何处理返回值类型？返回 str、bytes、Image 时分别对应什么 MCP 内容块？",
        ground_truth_answer=(
            "FastMCP 自动将工具返回值转换为适当的 MCP 内容块：\n"
            "- str → TextContent\n"
            "- bytes → Base64 编码后作为 BlobResourceContents\n"
            "- Image → ImageContent\n"
            "- Audio → AudioContent\n"
            "- File → base64 编码的 EmbeddedResource\n"
            "- MCP SDK 内容块 → 按原样发送\n"
            "- 以上任意类型的列表 → 根据上述规则转换每个项目\n"
            "- None → 空响应"
        ),
        relevant_contexts=[
            "FastMCP 自动将工具返回值转换为适当的 MCP 内容块：\n\n"
            "- **`str`**：作为 `TextContent` 发送\n"
            "- **`bytes`**：Base64 编码后作为 `BlobResourceContents` 发送\n"
            "- **`fastmcp.utilities.types.Image`**：作为 `ImageContent` 发送\n"
            "- **`fastmcp.utilities.types.Audio`**：作为 `AudioContent` 发送\n"
            "- **`fastmcp.utilities.types.File`**：作为 base64 编码的 `EmbeddedResource` 发送\n"
            "- **MCP SDK 内容块**：按原样发送\n"
            "- **以上任意类型的列表**：根据上述规则转换每个项目\n"
            "- **`None`**：导致空响应",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    EvalQuestion(
        id="ev005",
        question="FastMCP 工具如何设置超时？超时后返回什么错误码？",
        ground_truth_answer=(
            "使用 @mcp.tool(timeout=30.0) 设置超时，以秒为单位的浮点数。\n"
            "超时后 FastMCP 返回 MCP 错误码 -32000。\n"
            "同步函数和异步函数都支持 timeout 参数。\n"
            "timeout 不适用于后台任务（task=True），因为后台任务在 Docket 工作器中执行，不强制执行 FastMCP 超时。"
        ),
        relevant_contexts=[
            "@mcp.tool(timeout=30.0)\n"
            "async def fetch_data(url: str) -> dict:\n"
            '    """使用 30 秒超时获取数据。"""',
            "当工具超过其超时时，FastMCP 返回带有代码 `-32000` 的 MCP 错误。",
            "timeout 参数**不**适用于后台任务。",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "usage", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 资源与提示词
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev006",
        question="FastMCP 中 @mcp.resource 装饰器必需的参数是什么？资源是什么时候执行的？",
        ground_truth_answer=(
            "@mcp.resource 必需的参数是 URI（第一个参数），用于标识资源的唯一地址。\n"
            "资源是延迟加载的——装饰函数仅在客户端通过 resources/read 请求该 URI 时执行，\n"
            "而不是在服务器启动时执行。\n"
            "资源名称取自函数名，资源描述取自函数的文档字符串。"
        ),
        relevant_contexts=[
            '@mcp.resource("resource://greeting")\n'
            "def get_greeting() -> str:\n"
            '    """提供一个简单的问候消息。"""\n'
            '    return "来自 FastMCP 资源的问候！"',
            "URI：@resource 的第一个参数是客户端用来请求此数据的唯一 URI",
            "延迟加载：装饰函数仅在客户端通过 resources/read 专门请求该资源 URI 时执行",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 后台任务
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev007",
        question="FastMCP 后台任务（task=True）有什么要求？支持哪三种执行模式？",
        ground_truth_answer=(
            "后台任务需要安装额外依赖：pip install 'fastmcp[tasks]'。\n"
            "后台任务要求函数必须是异步的（async def），尝试与同步函数一起使用会引发 ValueError。\n"
            "三种执行模式通过 TaskConfig 设置：\n"
            "- forbidden：客户端无任务调用时同步执行，有任务调用时返回错误\n"
            "- optional：客户端无任务调用时同步执行，有任务调用时作为后台任务执行\n"
            "- required：客户端无任务调用时返回错误，有任务调用时作为后台任务执行"
        ),
        relevant_contexts=[
            'pip install "fastmcp[tasks]"',
            "后台任务需要异步函数。尝试将 `task=True` 与同步函数一起使用会在注册时引发 `ValueError`。",
            "「forbidden」「optional」「required」",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "usage", "difficulty": "hard"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 提供者
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev008",
        question="FastMCP 有哪些内置提供者（Provider）？各有什么作用？",
        ground_truth_answer=(
            "三种内置提供者：\n"
            "1. LocalProvider：存储你在代码中定义的组件，使用 @mcp.tool、mcp.add_tool() 等\n"
            "2. FastMCPProvider：包装另一个 FastMCP 服务器，使用 mcp.mount(server) 挂载\n"
            "3. ProxyProvider：连接到远程 MCP 服务器，使用 create_proxy(client) 创建\n\n"
            "大多数用户只与 LocalProvider 交互。提供者按注册顺序查询，LocalProvider 始终是第一个。"
        ),
        relevant_contexts=[
            "| `LocalProvider` | 存储你在代码中定义的组件 | `@mcp.tool`, `mcp.add_tool()` |\n"
            "| `FastMCPProvider` | 包装另一个 FastMCP 服务器 | `mcp.mount(server)` |\n"
            "| `ProxyProvider` | 连接到远程 MCP 服务器 | `create_proxy(client)` |",
            "LocalProvider 始终是第一个。",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 依赖注入
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev009",
        question="FastMCP 的依赖注入如何工作？使用 Depends 的参数会暴露给 LLM 吗？",
        ground_truth_answer=(
            "FastMCP 使用依赖注入为工具提供运行时值。声明一个具有可识别类型注解或依赖默认值的参数，"
            "FastMCP 在运行时自动注入解析后的值。\n"
            "使用 Depends() 的参数会自动从工具模式中排除——客户端永远不会将它们视为可调用参数。\n"
            "典型用途：注入 user_id、凭据或数据库连接而不暴露给 LLM。\n"
            "例：def get_user_details(user_id: str = Depends(get_user_id)) -> str"
        ),
        relevant_contexts=[
            "依赖参数会自动从 MCP 模式中排除——客户端永远不会将它们视为可调用参数。",
            "@mcp.tool\n"
            "def get_user_details(user_id: str = Depends(get_user_id)) -> str:\n"
            "    # user_id 由服务器注入，而非 LLM 提供\n"
            '    return f"用户 {user_id} 的详细信息"',
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 认证
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev010",
        question="FastMCP JWT 令牌验证支持哪三种密钥方式？HMAC 方式有什么要求？",
        ground_truth_answer=(
            "三种方式：\n"
            "1. JWKS 端点集成：使用 jwks_uri 从远端获取公钥\n"
            "2. 对称密钥验证（HMAC）：使用 public_key 参数传入共享密钥，algorithm='HS256'\n"
            "3. 静态公钥验证：直接传入 PEM 格式的公钥字符串\n\n"
            "HMAC 方式要求：密钥长度至少 32 个字符（your-shared-secret-key-minimum-32-chars），\n"
            "同时需要指定 issuer 和 audience。"
        ),
        relevant_contexts=[
            "verifier = JWTVerifier(\n"
            '    jwks_uri="https://auth.yourcompany.com/.well-known/jwks.json",\n'
            '    issuer="https://auth.yourcompany.com",\n'
            '    audience="mcp-production-api"\n'
            ")",
            "verifier = JWTVerifier(\n"
            '    public_key="your-shared-secret-key-minimum-32-chars",\n'
            '    issuer="internal-auth-service",\n'
            '    audience="mcp-internal-api",\n'
            '    algorithm="HS256"\n'
            ")",
            "verifier = JWTVerifier(\n"
            "    public_key=public_key_pem,\n"
            '    issuer="https://auth.yourcompany.com",\n'
            '    audience="mcp-production-api"\n'
            ")",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "security", "difficulty": "hard"},
    ),
    EvalQuestion(
        id="ev011",
        question="FastMCP 支持不透明令牌验证吗？怎么配置？",
        ground_truth_answer=(
            "支持。通过 OAuth 2.0 令牌内省（RFC 7662）实现不透明令牌验证。\n"
            "使用 IntrospectionTokenVerifier 类，需要配置：\n"
            "- introspection_url：内省端点地址\n"
            "- client_id：资源服务器客户端 ID\n"
            "- client_secret：客户端密钥\n"
            "- required_scopes：必需的权限范围列表"
        ),
        relevant_contexts=[
            "from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier\n\n"
            "verifier = IntrospectionTokenVerifier(\n"
            '    introspection_url="https://auth.yourcompany.com/oauth/introspect",\n'
            '    client_id="mcp-resource-server",\n'
            '    client_secret="your-client-secret",\n'
            '    required_scopes=["api:read", "api:write"]\n'
            ")",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "security", "difficulty": "hard"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — HTTP 部署
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev012",
        question="FastMCP 服务器通过 HTTP 部署有哪两种方式？",
        ground_truth_answer=(
            "两种方式：\n"
            "1. 直接 HTTP 服务器：mcp.run(transport='http', host='0.0.0.0', port=8000)\n"
            "2. ASGI 应用：app = mcp.http_app()，然后使用 Uvicorn 运行\n\n"
            "ASGI 方式示例：uvicorn app:app --host 0.0.0.0 --port 8000\n\n"
            "还可以自定义路径（mcp.run(path='/api/mcp/')）、添加健康检查端点"
            "（@mcp.custom_route('/health')）和自定义中间件。"
        ),
        relevant_contexts=[
            'mcp.run(transport="http", host="0.0.0.0", port=8000)',
            "app = mcp.http_app()",
            "uvicorn app:app --host 0.0.0.0 --port 8000",
            'mcp.run(transport="http", host="0.0.0.0", port=8000, path="/api/mcp/")',
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "deployment", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 中间件
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev013",
        question="FastMCP 中间件的执行顺序是怎样的？如何实现一个简单的日志中间件？",
        ground_truth_answer=(
            "MCP 中间件在服务器操作周围形成一个管道。请求按注册顺序流经每个中间件，"
            "响应以相反顺序返回。\n"
            "请求 → 中间件 A → 中间件 B → 处理器 → 中间件 B → 中间件 A → 响应\n\n"
            "日志中间件示例：\n"
            "class LoggingMiddleware(Middleware):\n"
            "    async def on_message(self, context: MiddlewareContext, call_next):\n"
            "        print(f'→ {context.method}')\n"
            "        result = await call_next(context)\n"
            "        print(f'← {context.method}')\n"
            "        return result\n\n"
            "通过 mcp.add_middleware(LoggingMiddleware()) 注册。"
        ),
        relevant_contexts=[
            "请求 → 中间件 A → 中间件 B → 处理器 → 中间件 B → 中间件 A → 响应",
            "class LoggingMiddleware(Middleware):\n"
            "    async def on_message(self, context: MiddlewareContext, call_next):\n"
            '        print(f"→ {context.method}")\n'
            "        result = await call_next(context)\n"
            '        print(f"← {context.method}")\n'
            "        return result",
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 工具错误处理
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev014",
        question="FastMCP 工具抛异常时默认会怎样？如何屏蔽内部错误详情？",
        ground_truth_answer=(
            "默认情况下，所有异常（包括其详细信息）都会被记录并转换为 MCP 错误响应"
            "发送回客户端 LLM。\n"
            "屏蔽内部错误详情的两种方式：\n"
            "1. 创建 FastMCP 实例时使用 mask_error_details=True 参数\n"
            "2. 使用 ToolError 显式控制发送给客户端的错误信息\n\n"
            "例：\n"
            "mcp = FastMCP(name='SecureServer', mask_error_details=True)\n\n"
            "raise ToolError('不允许除以零。')"
        ),
        relevant_contexts=[
            "默认情况下，所有异常（包括其详细信息）都会被记录并转换为 MCP 错误响应发送回客户端 LLM。",
            'mcp = FastMCP(name="SecureServer", mask_error_details=True)',
            'from fastmcp.exceptions import ToolError\n\nraise ToolError("不允许除以零。")',
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "usage", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — FastAPI 集成
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev015",
        question="FastMCP 与 FastAPI 集成有哪两种方式？",
        ground_truth_answer=(
            "两种方式：\n"
            "1. 从 FastAPI 应用生成 MCP 服务器：将现有 API 端点转换为 MCP 工具，"
            "底层使用 OpenAPIProvider 从 FastAPI 的 OpenAPI 规范中获取工具\n"
            "2. 将 MCP 服务器挂载到 FastAPI 应用中：为 Web 应用添加 MCP 功能\n\n"
            "注意：从 OpenAPI 生成 MCP 服务器适合原型设计，"
            "但精心设计的 MCP 服务器性能显著优于自动转换的 OpenAPI 服务器。"
            "FastMCP 不包含 FastAPI 作为依赖项，需单独安装。"
        ),
        relevant_contexts=[
            "1. **[从 FastAPI 应用生成 MCP 服务器](#generating-an-mcp-server)** - 将现有 API 端点转换为 MCP 工具\n"
            "2. **[将 MCP 服务器挂载到 FastAPI 应用中](#mounting-an-mcp-server)** - 为您的 Web 应用程序添加 MCP 功能",
            "FastMCP 的*不*包含 FastAPI 作为依赖项；您需要单独安装它以使用此集成。",
        ],
        relevant_document_ids=["doc_fastmcp_integrations"],
        metadata={"category": "integration", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastMCP — 工具参数隐藏
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev016",
        question="FastMCP 如何对 LLM 隐藏某些工具参数？",
        ground_truth_answer=(
            "使用 Depends() 进行依赖注入。使用 Depends() 的参数会自动从工具模式中排除，\n"
            "LLM 永远不会将它们视为可调用参数。典型用途包括注入 user_id、凭据或数据库连接。\n\n"
            "示例：\n"
            "from fastmcp.dependencies import Depends\n\n"
            "def get_user_id() -> str:\n"
            "    return 'user_123'\n\n"
            "@mcp.tool\n"
            "def get_user_details(user_id: str = Depends(get_user_id)) -> str:\n"
            "    return f'用户 {user_id} 的详细信息'\n\n"
            "此外，使用 Annotated + Field 可以添加参数描述和验证约束，"
            "但 LLM 仍然可以看到该参数。"
        ),
        relevant_contexts=[
            "对 LLM 隐藏参数\n\n"
            "要在运行时注入值而不暴露给 LLM（如 user_id、凭据或数据库连接），使用 Depends() 进行依赖注入。"
            "使用 Depends() 的参数会自动从工具模式中排除",
            "@mcp.tool\n"
            "def get_user_details(user_id: str = Depends(get_user_id)) -> str:\n"
            "    # user_id 由服务器注入，而非 LLM 提供\n"
            '    return f"用户 {user_id} 的详细信息"',
        ],
        relevant_document_ids=["doc_fastmcp_servers"],
        metadata={"category": "reference", "difficulty": "hard"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastAPI 学习笔记
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev017",
        question="FastAPI 中如何定义带路径参数的接口？路径参数的类型声明有什么作用？",
        ground_truth_answer=(
            "用 {参数名} 在 URL 中声明路径变量。\n\n"
            "示例：\n"
            "@app.get('/items/{item_id}')\n"
            "async def read_item(item_id: int):\n"
            "    return {'item_id': item_id}\n\n"
            "类型声明的作用：\n"
            "1. 数据解析：URL 字符串自动转为 Python 类型（如 '3' → 3）\n"
            "2. 数据验证：类型不匹配返回清晰 JSON 错误\n"
            "3. API 文档：自动生成 Swagger UI + ReDoc\n\n"
            "特殊语法：使用 :path 匹配任意子路径，如 @app.get('/files/{file_path:path}')"
        ),
        relevant_contexts=[
            '@app.get("/items/{item_id}")\n'
            "async def read_item(item_id: int):\n"
            '    return {"item_id": item_id}',
            "| 能力 | 说明 |\n"
            "|------|------|\n"
            '| 数据解析 | URL 字符串自动转为 Python 类型（如 `"3"` → `3`） |\n'
            "| 数据验证 | 类型不匹配返回清晰 JSON 错误 |\n"
            "| API 文档 | 自动生成 Swagger UI + ReDoc |",
            '@app.get("/files/{file_path:path}")  # :path 匹配任意子路径',
        ],
        relevant_document_ids=["doc_fastapi_notes"],
        metadata={"category": "reference", "difficulty": "easy"},
    ),
    EvalQuestion(
        id="ev018",
        question="FastAPI 查询参数模型是什么？怎么用？",
        ground_truth_answer=(
            "FastAPI 支持使用 Pydantic 模型声明查询参数组，通过 @app.get() 的 Query 依赖注入。\n"
            "这样可以将多个查询参数组织在一个模型类中，而不是分散在函数参数里。\n\n"
            "示例：\n"
            "class FilterParams(BaseModel):\n"
            "    category: str | None = None\n"
            "    max_price: float | None = None\n\n"
            "@app.get('/products')\n"
            "def list_products(params: FilterParams = Query()):\n"
            "    ..."
        ),
        relevant_contexts=[
            "## 查询参数模型",
            "class FilterParams(BaseModel):\n"
            "    category: str | None = None\n"
            "    max_price: float | None = None",
        ],
        relevant_document_ids=["doc_fastapi_notes"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastAPI — 文件上传
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev019",
        question="FastAPI 如何接收上传的文件？UploadFile 和 bytes 两种方式有什么区别？",
        ground_truth_answer=(
            "使用 File 依赖声明文件参数。两种方式：\n\n"
            "1. bytes 方式：适用于小文件\n"
            "   async def upload(file: bytes = File())\n\n"
            "2. UploadFile 方式：适用于大文件，提供更多功能\n"
            "   async def upload(file: UploadFile = File())\n"
            "   UploadFile 属性：filename、content_type、size\n"
            "   方法：read()、write()、seek()、close()\n\n"
            "UploadFile 优势：不一次性读入内存，适合大文件；"
            "提供文件名、内容类型等元数据。"
        ),
        relevant_contexts=[
            "## 请求文件",
            "async def upload(file: bytes = File()):",
            "async def upload(file: UploadFile = File()):",
        ],
        relevant_document_ids=["doc_fastapi_notes"],
        metadata={"category": "usage", "difficulty": "easy"},
    ),
    # ══════════════════════════════════════════════════════════════════════
    # FastAPI — 响应模型
    # ══════════════════════════════════════════════════════════════════════
    EvalQuestion(
        id="ev020",
        question="FastAPI 响应模型如何控制返回数据的字段？什么是 response_model_exclude_unset？",
        ground_truth_answer=(
            "使用 response_model 参数指定返回数据的 Pydantic 模型。\n"
            "@app.get('/items', response_model=ItemResponse)\n\n"
            "常用参数：\n"
            "- response_model_exclude_unset=True：只返回显式设置过的字段（不返回默认值）\n"
            "- response_model_include：仅返回指定字段\n"
            "- response_model_exclude：排除指定字段\n\n"
            "额外模型可以通过继承或组合 Pydantic 模型来实现输出不同字段的需求。"
        ),
        relevant_contexts=[
            "## 响应模型 - 返回类型",
            "## 额外模型",
            "response_model_exclude_unset=True",
        ],
        relevant_document_ids=["doc_fastapi_notes"],
        metadata={"category": "reference", "difficulty": "medium"},
    ),
]
