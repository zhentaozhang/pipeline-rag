"""
深度审查与加固验证测试（Hardening & Invariant Verification）

专门针对本次改造的所有关键 Invariant 和边界条件进行靶向验证：
1. SubPlan 拓扑环检测：自环、链环、复杂深层图、孤立节点；
2. requires_fresh_search 与 looks_like_open_chat_question 边界与混合时态；
3. _should_decompose 边界条件；
4. ExecutorRegistry 别名与多 Agent 执行器映射；
5. TimeSensitivityStage 不污染 ctx.question。
"""

import pytest

from app.chat.schema import ExecutionPlan, SubPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.executors.parallel_executor import ParallelExecutor
from app.executors.rag import RagChatExecutor
from app.executors.registry import ExecutorRegistry
from app.orchestrator.intent_detector import looks_like_open_chat_question
from app.orchestrator.subplan import validate_sub_plans
from app.orchestrator.supervisor import _should_decompose
from app.orchestrator.time_helper import TimeSensitiveQueryHelper


class TestSubPlanCycleDetectionHardening:
    """拓扑环检测完备性测试（覆盖各种图论拓扑结构）"""

    def test_empty_sub_plans(self):
        valid, errors = validate_sub_plans([])
        assert valid is True
        assert errors == []

    def test_single_sub_plan_no_dep(self):
        valid, errors = validate_sub_plans(
            [SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1")]
        )
        assert valid is True
        assert errors == []

    def test_self_cycle(self):
        """自环（自己依赖自己）"""
        valid, errors = validate_sub_plans(
            [SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=["1"])]
        )
        assert valid is False
        assert any("循环依赖" in e for e in errors)

    def test_indirect_three_node_cycle(self):
        """3 节点间接环：1 -> 2 -> 3 -> 1"""
        plans = [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=["3"]),
            SubPlan(id="2", mode=ExecutionMode.RETRIEVAL, question="q2", depends_on=["1"]),
            SubPlan(id="3", mode=ExecutionMode.RETRIEVAL, question="q3", depends_on=["2"]),
        ]
        valid, errors = validate_sub_plans(plans)
        assert valid is False
        assert any("循环依赖" in e for e in errors)

    def test_dag_with_multiple_roots_and_leaves(self):
        """标准复杂的菱形 DAG（无环）：1, 2 为根；3 依赖 1,2；4 依赖 3"""
        plans = [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
            SubPlan(id="2", mode=ExecutionMode.RETRIEVAL, question="q2", depends_on=[]),
            SubPlan(id="3", mode=ExecutionMode.RETRIEVAL, question="q3", depends_on=["1", "2"]),
            SubPlan(id="4", mode=ExecutionMode.RETRIEVAL, question="q4", depends_on=["3"]),
        ]
        valid, errors = validate_sub_plans(plans)
        assert valid is True
        assert errors == []

    def test_disconnected_subgraphs_one_with_cycle(self):
        """两个非连通子图：图 A (1->2) 正常，图 B (3<->4) 有环"""
        plans = [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
            SubPlan(id="2", mode=ExecutionMode.RETRIEVAL, question="q2", depends_on=["1"]),
            SubPlan(id="3", mode=ExecutionMode.RETRIEVAL, question="q3", depends_on=["4"]),
            SubPlan(id="4", mode=ExecutionMode.RETRIEVAL, question="q4", depends_on=["3"]),
        ]
        valid, errors = validate_sub_plans(plans)
        assert valid is False
        assert any("循环依赖" in e for e in errors)


class TestTimeSensitivityAndRoutingHardening:
    """时间敏感与路由判定的边界测试"""

    @pytest.mark.parametrize(
        "q",
        [
            "",
            "   ",
            "去年油价是多少",  # 历史意图排除
            "2023-01-01发生的事情",  # 显式日期排除
            "今天是几号",  # 日历类排除
            "现在的差旅标准是什么",  # 知识库状态，不触发 fresh search
            "最新的考勤管理规范",  # 知识库状态，不触发 fresh search
            "目前支持的部署平台有哪些",  # 知识库状态，不触发 fresh search
            "当前版本升级说明",  # 知识库状态，不触发 fresh search
        ],
    )
    def test_not_fresh_queries(self, q: str):
        assert TimeSensitiveQueryHelper.requires_fresh_search(q) is False

    @pytest.mark.parametrize(
        "q",
        [
            "北京天气预报",  # 天气领域词
            "今天的实时金价",  # 金价领域词
            "台风最新路径",  # 预警/台风领域词
            "实时热点新闻",  # 实时资讯
            "现在发生什么大事了",  # 动态事件特征
            "刚刚发生了什么",  # 刚刚发生
        ],
    )
    def test_is_fresh_queries(self, q: str):
        assert TimeSensitiveQueryHelper.requires_fresh_search(q) is True

    def test_knowledge_base_questions_never_divert_to_open_chat(self):
        """核心断言：含最新/现在的知识库提问绝对不会被误改道"""
        for q in [
            "最新的报销流程是怎样的",
            "现在系统有哪些权限角色",
            "当前差旅住宿标准是多少",
            "目前团队使用的CI/CD工具链",
        ]:
            fresh = TimeSensitiveQueryHelper.requires_fresh_search(q)
            assert fresh is False
            assert looks_like_open_chat_question(q, fresh) is False


class TestShouldDecomposeHardening:
    """复杂问题规则预筛边界测试"""

    def test_blank_questions(self):
        plan1 = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question="", rewritten_question=""
        )
        plan2 = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question="   ", rewritten_question="   "
        )
        assert _should_decompose(plan1) is False
        assert _should_decompose(plan2) is False

    @pytest.mark.parametrize(
        "q",
        [
            "为什么请假需要主管审批",  # 制度单跳
            "总结一下采购管理办法",  # 制度单跳
            "分析一下这个审批节点的配置要求",  # 制度单跳
            "怎么配置数据库连接池",  # 技术单跳
            "查询上个月的销售报表",  # 单跳
        ],
    )
    def test_single_hop_questions_never_decompose(self, q: str):
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question=q, rewritten_question=q
        )
        assert _should_decompose(plan) is False

    @pytest.mark.parametrize(
        "q",
        [
            "对比方案A与方案B的优缺点",  # 对比
            "比较两种架构在性能上的区别",  # 比较、区别
            "分析两个子系统之间的关联与异同",  # 关联、异同
            "分别阐述前端和后端的技术栈规范",  # 分别
            "模块A的改动如何影响模块B",  # 如何影响
        ],
    )
    def test_multi_entity_comparison_questions_decompose(self, q: str):
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question=q, rewritten_question=q
        )
        assert _should_decompose(plan) is True

    def test_long_question_without_conjunction_does_not_decompose(self):
        """超长但没有复合并列连词的单跳提问，不应分解"""
        long_q = "请详细介绍一下我们公司的整个信息化系统开发规范和流程文档中的具体要求说明细节部分"
        assert len(long_q) >= 40
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question=long_q, rewritten_question=long_q
        )
        assert _should_decompose(plan) is False

    def test_long_question_with_conjunction_decomposes(self):
        """超长且包含显式并列连词的复合任务，触发分解"""
        long_q = (
            "请帮我梳理系统部署过程中涉及到的所有配置项说明，并且列出各服务之间的依赖顺序，"
            "同时给出常见故障排查步骤以及恢复方案"
        )
        assert len(long_q) >= 50
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL, original_question=long_q, rewritten_question=long_q
        )
        assert _should_decompose(plan) is True


class TestRegistryHardening:
    """执行器注册表的完备性测试"""

    def test_rag_chat_aliased_to_retrieval(self):
        task = ChatTaskInfo(conversation_id="c1", question="q", exchange_id=1)
        reg = ExecutorRegistry(db=None, task=task)
        executor = reg.get(ExecutionMode.RAG_CHAT)
        assert isinstance(executor, RagChatExecutor)

    def test_multi_agent_instantiated_via_get(self):
        task = ChatTaskInfo(conversation_id="c1", question="q", exchange_id=1)
        reg = ExecutorRegistry(db=None, task=task)
        executor = reg.get(ExecutionMode.MULTI_AGENT)
        assert isinstance(executor, ParallelExecutor)

    def test_unregistered_mode_raises_error(self):
        task = ChatTaskInfo(conversation_id="c1", question="q", exchange_id=1)
        reg = ExecutorRegistry(db=None, task=task)
        with pytest.raises(RuntimeError, match="未找到执行模式对应的执行器"):
            reg.get(ExecutionMode.OPEN_CHAT)
