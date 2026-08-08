import pytest

from app.common.enums import (
    BusinessStatus,
    ChatQueryMode,
    ChatSessionStatus,
    ChatTurnStatus,
    ConversationTraceStageState,
    DocumentChunkSourceTypeEnum,
    DocumentFileTypeEnum,
    DocumentIndexStatusEnum,
    DocumentNavigationAction,
    DocumentOperatorTypeEnum,
    DocumentPipelineStageEnum,
    DocumentStorageTypeEnum,
    DocumentStrategyRoleEnum,
    DocumentStrategyStatusEnum,
    DocumentStructureNodeTypeEnum,
    DocumentTaskEventTypeEnum,
    DocumentTaskStageEnum,
    DocumentTaskStatusEnum,
    DocumentTaskTypeEnum,
    ExecutionMode,
    NavigationScopeMode,
    TraceStageCodeEnum,
    normalize_chat_mode,
)


class TestDocumentEnums:
    def test_task_types(self):
        assert DocumentTaskTypeEnum.PARSE_ROUTE == 1
        assert DocumentTaskTypeEnum.BUILD_INDEX == 2

    def test_task_stage(self):
        assert DocumentTaskStageEnum.FILE_UPLOAD == 1
        assert DocumentTaskStageEnum.CHUNK_EXECUTE == 5
        assert DocumentTaskStageEnum.STORE_COMPLETE == 8

    def test_strategy_role(self):
        assert DocumentStrategyRoleEnum.PRIMARY == 1
        assert DocumentStrategyRoleEnum.OPTIMIZE == 2
        assert DocumentStrategyRoleEnum.FALLBACK == 3
        assert DocumentStrategyRoleEnum.ENHANCE == 4

    def test_index_status(self):
        assert DocumentIndexStatusEnum.WAIT_BUILD == 1
        assert DocumentIndexStatusEnum.BUILDING == 2
        assert DocumentIndexStatusEnum.BUILD_SUCCESS == 3
        assert DocumentIndexStatusEnum.BUILD_FAILED == 4

    def test_structure_node_types(self):
        assert DocumentStructureNodeTypeEnum.DOCUMENT == 1
        assert DocumentStructureNodeTypeEnum.SECTION == 2
        assert DocumentStructureNodeTypeEnum.STEP == 3
        assert DocumentStructureNodeTypeEnum.LIST_ITEM == 4

    def test_pipeline_stage(self):
        assert DocumentPipelineStageEnum.INIT == 0
        assert DocumentPipelineStageEnum.PARSED == 1
        assert DocumentPipelineStageEnum.CHUNKED == 2
        assert DocumentPipelineStageEnum.VECTORIZED == 3
        assert DocumentPipelineStageEnum.INDEXED == 4
        assert DocumentPipelineStageEnum.PROFILED == 5
        assert DocumentPipelineStageEnum.FAILED == -1

    def test_navigation_action(self):
        assert DocumentNavigationAction.TOPIC_CONTINUE.value == "TOPIC_CONTINUE"
        assert DocumentNavigationAction.CHILD_DESCEND.value == "CHILD_DESCEND"
        assert DocumentNavigationAction.ITEM_REFERENCE.value == "ITEM_REFERENCE"
        assert DocumentNavigationAction.UNKNOWN.value == "UNKNOWN"

    def test_other_statuses(self):
        assert DocumentChunkSourceTypeEnum.ORIGINAL == 1
        assert DocumentChunkSourceTypeEnum.ENRICHED == 2
        assert DocumentStorageTypeEnum.MINIO == 1
        assert DocumentTaskStatusEnum.NEW == 1
        assert DocumentTaskStatusEnum.CANCELED == 5
        assert DocumentStrategyStatusEnum.CONFIRMED == 3
        assert DocumentOperatorTypeEnum.ADMIN == 3
        assert DocumentFileTypeEnum.PDF == 1
        assert DocumentFileTypeEnum.HTML == 6
        assert DocumentTaskEventTypeEnum.USER_CONFIRM == 6


class TestChatEnums:
    def test_chat_query_mode_values(self):
        assert ChatQueryMode.DOCUMENT == 1
        assert ChatQueryMode.OPEN_CHAT == 2
        assert ChatQueryMode.AUTO_DOCUMENT == 3

    def test_normalize_chat_mode(self):
        assert normalize_chat_mode("auto") == ChatQueryMode.AUTO_DOCUMENT
        assert normalize_chat_mode("auto_document") == ChatQueryMode.AUTO_DOCUMENT
        assert normalize_chat_mode("document") == ChatQueryMode.DOCUMENT
        assert normalize_chat_mode("doc") == ChatQueryMode.DOCUMENT
        assert normalize_chat_mode("open_chat") == ChatQueryMode.OPEN_CHAT
        assert normalize_chat_mode("openchat") == ChatQueryMode.OPEN_CHAT
        assert normalize_chat_mode("OPEN_CHAT") == ChatQueryMode.OPEN_CHAT

    def test_normalize_chat_mode_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_chat_mode("not_a_mode")

    def test_execution_mode(self):
        assert ExecutionMode.RETRIEVAL.value == "RETRIEVAL"
        assert ExecutionMode.REACT_AGENT.value == "REACT_AGENT"
        assert ExecutionMode.CLARIFICATION.value == "CLARIFICATION"
        assert ExecutionMode.GRAPH_ONLY.value == "GRAPH_ONLY"
        assert ExecutionMode.GRAPH_THEN_EVIDENCE.value == "GRAPH_THEN_EVIDENCE"
        assert ExecutionMode.REFUSAL.value == "REFUSAL"
        assert ExecutionMode.MULTI_AGENT.value == "MULTI_AGENT"

    def test_session_and_turn_status(self):
        assert ChatSessionStatus.IDLE == 1
        assert ChatSessionStatus.RUNNING == 2
        assert ChatTurnStatus.RUNNING == 1
        assert ChatTurnStatus.STOPPED == 4


class TestTraceEnums:
    def test_trace_stage_codes(self):
        assert TraceStageCodeEnum.MEMORY.value == "MEMORY"
        assert TraceStageCodeEnum.ROUTE.value == "ROUTE"
        assert TraceStageCodeEnum.RAG_RETRIEVE.value == "RAG_RETRIEVE"
        assert TraceStageCodeEnum.FINALIZE.value == "FINALIZE"

    def test_trace_stage_state(self):
        assert ConversationTraceStageState.RUNNING == 1
        assert ConversationTraceStageState.COMPLETED == 2
        assert ConversationTraceStageState.FAILED == 3
        assert ConversationTraceStageState.SKIPPED == 4

    def test_navigation_scope_mode(self):
        assert NavigationScopeMode.SOFT == 0
        assert NavigationScopeMode.HARD_SECTION == 1
        assert NavigationScopeMode.HARD_ITEM == 2
        assert NavigationScopeMode.HARD_PARENT_WITH_SIBLINGS == 3

    def test_business_status(self):
        assert BusinessStatus.NO == 0
        assert BusinessStatus.YES == 1
