from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

from agent.memory_kernel.interfaces import KernelCitation, KernelItem, KernelRequest, KernelResult, QueryRoute, RetrievalOutput


class FakeMemoryKernel:
    def __init__(self, *, context_block: str, payload: dict, route_type: str = "enterprise_retrieval") -> None:
        self.context_block = context_block
        self.payload = payload
        self.route_type = route_type
        self.requests: list[KernelRequest] = []

    def start_turn(self, request: KernelRequest) -> KernelResult:
        self.requests.append(request)
        retrieval = RetrievalOutput(
            items=[
                KernelItem(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    version_id="ver-1",
                    text="投标截止日期为2025年5月20日。",
                    heading_path=["第一章", "项目概况"],
                    page_start=3,
                    page_end=3,
                )
            ] if self.context_block else [],
            citations=[
                KernelCitation(
                    document_id="doc-1",
                    version_id="ver-1",
                    chunk_id="chunk-1",
                    source_name="2025 招标资料汇编",
                    heading_path=["第一章", "项目概况"],
                    page_start=3,
                    page_end=3,
                    quote_text="投标截止日期为2025年5月20日。",
                )
            ] if self.context_block else [],
            backend=self.payload.get("backend", "hermes_memory"),
            dense_retrieval_status=self.payload.get("dense_retrieval_status", "not_executed"),
            trace={},
        )
        return KernelResult(
            route=QueryRoute(self.route_type, bool(self.context_block), "fake route"),
            retrieval=retrieval,
            context_block=self.context_block,
            trace={"enabled": True},
        )

    def finish_turn(self, request: KernelRequest, response: str, result: KernelResult) -> None:
        return None

    def result_payload(self, result: KernelResult) -> dict:
        return self.payload


class FakeMemoryManager:
    def __init__(self, prefetch: str = "") -> None:
        self.prefetch = prefetch
        self.turn_starts: list[tuple[int, str]] = []
        self.synced: list[tuple[str, str]] = []

    def on_turn_start(self, turn_number: int, message: str) -> None:
        self.turn_starts.append((turn_number, message))

    def prefetch_all(self, query: str) -> str:
        return self.prefetch

    def sync_all(self, user: str, assistant: str) -> None:
        self.synced.append((user, assistant))

    def queue_prefetch_all(self, query: str) -> None:
        return None


def _fake_chat_response(text: str = "ok"):
    return SimpleNamespace(
        model="fake-model",
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=text, tool_calls=None),
            )
        ],
    )


def _make_agent():
    _install_lightweight_run_agent_stubs()
    run_agent = importlib.import_module("run_agent")
    AIAgent = run_agent.AIAgent
    return AIAgent(
        model="test/model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        provider="custom",
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        max_iterations=2,
    )


def _install_lightweight_run_agent_stubs() -> None:
    if "model_tools" not in sys.modules:
        model_tools = types.ModuleType("model_tools")
        model_tools.get_tool_definitions = lambda *args, **kwargs: []
        model_tools.get_toolset_for_tool = lambda *args, **kwargs: None
        model_tools.handle_function_call = lambda *args, **kwargs: ""
        model_tools.check_toolset_requirements = lambda *args, **kwargs: {}
        sys.modules["model_tools"] = model_tools

    if "tools.terminal_tool" not in sys.modules:
        terminal_tool = types.ModuleType("tools.terminal_tool")
        terminal_tool.cleanup_vm = lambda *args, **kwargs: None
        terminal_tool.get_active_env = lambda *args, **kwargs: None
        terminal_tool.is_persistent_env = lambda *args, **kwargs: False
        sys.modules["tools.terminal_tool"] = terminal_tool

    if "tools.tool_result_storage" not in sys.modules:
        tool_result_storage = types.ModuleType("tools.tool_result_storage")
        tool_result_storage.maybe_persist_tool_result = lambda *args, **kwargs: None
        tool_result_storage.enforce_turn_budget = lambda *args, **kwargs: None
        sys.modules["tools.tool_result_storage"] = tool_result_storage

    if "tools.browser_tool" not in sys.modules:
        browser_tool = types.ModuleType("tools.browser_tool")
        browser_tool.cleanup_browser = lambda *args, **kwargs: None
        sys.modules["tools.browser_tool"] = browser_tool


def test_run_conversation_injects_contexts_in_policy_order(monkeypatch):
    captured = {}
    kernel_context = (
        "<enterprise-memory-context>\n"
        "enterprise evidence\n"
        "</enterprise-memory-context>"
    )
    kernel_payload = {
        "route": {"route_type": "enterprise_retrieval", "needs_retrieval": True, "reason": "fake", "mode": "bm25_first"},
        "backend": "database_fallback",
        "dense_retrieval_status": "not_executed",
        "citations": [{"chunk_id": "chunk-1"}],
        "trace": {"raw_path": "/Users/private/source.docx", "source_uri": "file:///Users/private/source.docx"},
    }
    agent = _make_agent()
    agent._memory_kernel = FakeMemoryKernel(context_block=kernel_context, payload=kernel_payload)
    agent._memory_kernel_config = SimpleNamespace(enabled=True, top_k=8)
    agent._memory_manager = FakeMemoryManager(prefetch="legacy memory says use internal naming")

    def fake_invoke_hook(name, **kwargs):
        if name == "pre_llm_call":
            return ["plugin context says be concise"]
        return []

    def fake_call(api_kwargs):
        captured["messages"] = api_kwargs["messages"]
        return _fake_chat_response("answer")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", fake_invoke_hook)
    monkeypatch.setattr(agent, "_interruptible_api_call", fake_call)
    monkeypatch.setattr(agent, "_interruptible_streaming_api_call", lambda api_kwargs, **kwargs: fake_call(api_kwargs))

    result = agent.run_conversation("请查一下投标截止日期")

    user_message = captured["messages"][-1]["content"]
    assert "<enterprise-memory-context>" in user_message
    assert "<memory-context>" in user_message
    assert "<plugin-context>" in user_message
    assert user_message.index("<enterprise-memory-context>") < user_message.index("<memory-context>")
    assert user_message.index("<memory-context>") < user_message.index("<plugin-context>")
    assert "must not override enterprise memory context" in user_message
    assert result["memory_kernel"]["backend"] == "database_fallback"
    assert result["memory_kernel"]["citations"][0]["chunk_id"] == "chunk-1"
    assert "/Users/private" not in str(result["memory_kernel"])
    assert "file:///Users" not in str(result["memory_kernel"])
    assert result["enterprise_memory"]["diagnostics_sanitized"] is True
    assert result["enterprise_memory"]["final_response_sanitized"] is True
    assert result["final_response"] == "answer"


def test_api_server_requires_enterprise_memory_tools_instead_of_hidden_context(monkeypatch):
    captured = {}
    kernel_context = (
        "<enterprise-memory-context>\n"
        "hidden enterprise evidence\n"
        "</enterprise-memory-context>"
    )
    kernel_payload = {
        "route": {"route_type": "enterprise_retrieval", "needs_retrieval": True, "reason": "fake", "mode": "bm25_first"},
        "backend": "database_fallback",
        "dense_retrieval_status": "not_executed",
        "citations": [{"chunk_id": "chunk-1"}],
        "trace": {},
    }
    agent = _make_agent()
    agent.platform = "api_server"
    agent._memory_kernel = FakeMemoryKernel(context_block=kernel_context, payload=kernel_payload)
    agent._memory_kernel_config = SimpleNamespace(enabled=True, top_k=8)
    agent._memory_manager = None

    def fake_invoke_hook(name, **kwargs):
        return []

    def fake_call(api_kwargs):
        captured["messages"] = api_kwargs["messages"]
        return _fake_chat_response("answer")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", fake_invoke_hook)
    monkeypatch.setattr(agent, "_interruptible_api_call", fake_call)
    monkeypatch.setattr(agent, "_interruptible_streaming_api_call", lambda api_kwargs, **kwargs: fake_call(api_kwargs))

    result = agent.run_conversation("围绕 @主标书 回答工程地点")

    user_message = captured["messages"][-1]["content"]
    assert "<enterprise-memory-context>" not in user_message
    assert result["memory_kernel"] is None
    assert result["enterprise_memory"]["hidden_pre_model_retrieval_used"] is False
    assert result["enterprise_memory"]["enterprise_memory_search_used"] is False


def test_run_conversation_unavailable_kernel_does_not_break_chat(monkeypatch):
    captured = {}
    kernel_payload = {
        "route": {"route_type": "enterprise_retrieval", "needs_retrieval": True, "reason": "fake", "mode": "bm25_first"},
        "backend": "unavailable",
        "dense_retrieval_status": "not_executed",
        "citations": [],
        "trace": {"error": "adapter unavailable"},
    }
    agent = _make_agent()
    agent._memory_kernel = FakeMemoryKernel(context_block="", payload=kernel_payload)
    agent._memory_kernel_config = SimpleNamespace(enabled=True, top_k=8)
    agent._memory_manager = None

    def fake_invoke_hook(name, **kwargs):
        return []

    def fake_call(api_kwargs):
        captured["messages"] = api_kwargs["messages"]
        return _fake_chat_response("plain answer")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", fake_invoke_hook)
    monkeypatch.setattr(agent, "_interruptible_api_call", fake_call)
    monkeypatch.setattr(agent, "_interruptible_streaming_api_call", lambda api_kwargs, **kwargs: fake_call(api_kwargs))

    result = agent.run_conversation("请查一下投标截止日期")

    user_message = captured["messages"][-1]["content"]
    assert "<enterprise-memory-context>" not in user_message
    assert result["final_response"] == "plain answer"
    assert result["memory_kernel"]["backend"] == "unavailable"
    assert result["memory_kernel"]["citations"] == []


def test_run_conversation_without_kernel_preserves_ordinary_chat(monkeypatch):
    captured = {}
    agent = _make_agent()
    agent._memory_kernel = None
    agent._memory_kernel_config = None
    agent._memory_manager = None

    def fake_invoke_hook(name, **kwargs):
        return []

    def fake_call(api_kwargs):
        captured["messages"] = api_kwargs["messages"]
        return _fake_chat_response("hello there")

    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", fake_invoke_hook)
    monkeypatch.setattr(agent, "_interruptible_api_call", fake_call)
    monkeypatch.setattr(agent, "_interruptible_streaming_api_call", lambda api_kwargs, **kwargs: fake_call(api_kwargs))

    result = agent.run_conversation("你好")

    user_message = captured["messages"][-1]["content"]
    assert "<enterprise-memory-context>" not in user_message
    assert "<memory-context>" not in user_message
    assert result["final_response"] == "hello there"
    assert "memory_kernel" in result
    assert result["memory_kernel"] is None
