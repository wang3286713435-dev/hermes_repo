"""Tests for hermes-api-server toolset and API server tool availability."""
import os
import json
from unittest.mock import patch, MagicMock

import pytest

from toolsets import resolve_toolset, get_toolset, validate_toolset

ENTERPRISE_MEMORY_TOOLS = {
    "enterprise_memory_search",
    "enterprise_memory_import_file",
    "enterprise_memory_find_files",
    "enterprise_memory_resolve_alias",
}


class TestHermesApiServerToolset:
    """Tests for the hermes-api-server toolset definition."""

    def test_toolset_exists(self):
        ts = get_toolset("hermes-api-server")
        assert ts is not None

    def test_toolset_validates(self):
        assert validate_toolset("hermes-api-server")

    def test_toolset_includes_web_tools(self):
        tools = resolve_toolset("hermes-api-server")
        assert "web_search" in tools
        assert "web_extract" in tools

    def test_toolset_includes_core_tools(self):
        tools = resolve_toolset("hermes-api-server")
        expected = [
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze", "image_generate",
            "execute_code", "delegate_task",
            "todo", "memory", "session_search", "cronjob",
        ]
        for tool in expected:
            assert tool in tools, f"Missing expected tool: {tool}"

    def test_toolset_includes_browser_tools(self):
        tools = resolve_toolset("hermes-api-server")
        for tool in ["browser_navigate", "browser_snapshot", "browser_click",
                      "browser_type", "browser_scroll", "browser_back",
                      "browser_press"]:
            assert tool in tools, f"Missing browser tool: {tool}"

    def test_toolset_includes_homeassistant_tools(self):
        tools = resolve_toolset("hermes-api-server")
        for tool in ["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"]:
            assert tool in tools, f"Missing HA tool: {tool}"

    def test_toolset_includes_enterprise_memory_tools(self):
        tools = resolve_toolset("hermes-api-server")

        assert ENTERPRISE_MEMORY_TOOLS.issubset(tools)

    def test_toolset_excludes_clarify(self):
        tools = resolve_toolset("hermes-api-server")
        assert "clarify" not in tools

    def test_toolset_excludes_send_message(self):
        tools = resolve_toolset("hermes-api-server")
        assert "send_message" not in tools

    def test_toolset_excludes_text_to_speech(self):
        tools = resolve_toolset("hermes-api-server")
        assert "text_to_speech" not in tools


class TestApiServerPlatformConfig:
    def test_platforms_dict_includes_api_server(self):
        from hermes_cli.tools_config import PLATFORMS
        assert "api_server" in PLATFORMS
        assert PLATFORMS["api_server"]["default_toolset"] == "hermes-api-server"

    def test_api_server_default_platform_toolsets_include_enterprise_memory(self):
        from hermes_cli.tools_config import _get_platform_tools

        toolsets = _get_platform_tools({}, "api_server")

        assert "enterprise_memory" in toolsets

    def test_api_server_default_tool_definitions_include_enterprise_memory(self):
        from hermes_cli.tools_config import _get_platform_tools
        from model_tools import get_tool_definitions

        toolsets = sorted(_get_platform_tools({}, "api_server"))
        definitions = get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
        names = {definition["function"]["name"] for definition in definitions}

        assert ENTERPRISE_MEMORY_TOOLS.issubset(names)


class TestApiServerAdapterToolset:
    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE", True)
    def test_create_agent_reads_config_toolsets(self):
        """API server resolves toolsets from config like all other platforms."""
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig

        adapter = APIServerAdapter(PlatformConfig())

        with patch("gateway.run._resolve_runtime_agent_kwargs") as mock_kwargs, \
             patch("gateway.run._resolve_gateway_model") as mock_model, \
             patch("gateway.run._load_gateway_config") as mock_config, \
             patch("run_agent.AIAgent") as mock_agent_cls:

            mock_kwargs.return_value = {"api_key": "test-key", "base_url": None,
                                        "provider": None, "api_mode": None,
                                        "command": None, "args": []}
            mock_model.return_value = "test/model"
            # No platform_toolsets override — should fall back to hermes-api-server default
            mock_config.return_value = {}
            mock_agent_cls.return_value = MagicMock()

            adapter._create_agent()

            mock_agent_cls.assert_called_once()
            call_kwargs = mock_agent_cls.call_args
            toolsets = call_kwargs.kwargs.get("enabled_toolsets")
            assert isinstance(toolsets, list)
            assert len(toolsets) > 0
            assert "enterprise_memory" in toolsets
            assert call_kwargs.kwargs.get("platform") == "api_server"

    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE", True)
    def test_create_agent_exposes_enterprise_memory_valid_tool_names(self):
        """API server-created agents must make enterprise memory model-visible."""
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig
        from model_tools import get_tool_definitions

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                self.enabled_toolsets = kwargs.get("enabled_toolsets")
                definitions = get_tool_definitions(
                    enabled_toolsets=self.enabled_toolsets,
                    quiet_mode=True,
                )
                self.valid_tool_names = {definition["function"]["name"] for definition in definitions}

        adapter = APIServerAdapter(PlatformConfig())

        with patch("gateway.run._resolve_runtime_agent_kwargs") as mock_kwargs, \
             patch("gateway.run._resolve_gateway_model") as mock_model, \
             patch("gateway.run._load_gateway_config") as mock_config, \
             patch("run_agent.AIAgent", FakeAgent):

            mock_kwargs.return_value = {"api_key": "test-key", "base_url": None,
                                        "provider": None, "api_mode": None,
                                        "command": None, "args": []}
            mock_model.return_value = "test/model"
            mock_config.return_value = {}

            agent = adapter._create_agent()

        assert ENTERPRISE_MEMORY_TOOLS.issubset(agent.valid_tool_names)

    @patch("gateway.platforms.api_server.AIOHTTP_AVAILABLE", True)
    def test_create_agent_respects_config_override(self):
        """User can override API server toolsets via platform_toolsets in config.yaml."""
        from gateway.platforms.api_server import APIServerAdapter
        from gateway.config import PlatformConfig

        adapter = APIServerAdapter(PlatformConfig())

        with patch("gateway.run._resolve_runtime_agent_kwargs") as mock_kwargs, \
             patch("gateway.run._resolve_gateway_model") as mock_model, \
             patch("gateway.run._load_gateway_config") as mock_config, \
             patch("run_agent.AIAgent") as mock_agent_cls:

            mock_kwargs.return_value = {"api_key": "test-key", "base_url": None,
                                        "provider": None, "api_mode": None,
                                        "command": None, "args": []}
            mock_model.return_value = "test/model"
            # User overrides with just web and terminal
            mock_config.return_value = {
                "platform_toolsets": {"api_server": ["web", "terminal"]}
            }
            mock_agent_cls.return_value = MagicMock()

            adapter._create_agent()

            mock_agent_cls.assert_called_once()
            call_kwargs = mock_agent_cls.call_args
            toolsets = call_kwargs.kwargs.get("enabled_toolsets")
            assert sorted(toolsets) == ["terminal", "web"]

    def test_enterprise_memory_live_route_diagnostics_reports_available_tools(self):
        from gateway.platforms.api_server import _build_enterprise_memory_live_route_diagnostics

        agent = MagicMock()
        agent.valid_tool_names = set(ENTERPRISE_MEMORY_TOOLS) | {"read_file", "search_files"}
        result = {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "enterprise_memory_search", "arguments": "{\"query\":\"@主标书\"}"}},
                    ],
                }
            ]
        }

        diagnostics = _build_enterprise_memory_live_route_diagnostics(agent, result)

        assert diagnostics["enterprise_memory_tools_available"] is True
        assert diagnostics["enterprise_memory_tools_sent_to_model"] is True
        assert diagnostics["enterprise_memory_tool_call_names"] == ["enterprise_memory_search"]
        assert diagnostics["enterprise_memory_tool_no_call_reason"] is None
        assert "/Users/" not in json.dumps(diagnostics)
        assert "file://" not in json.dumps(diagnostics)

    def test_enterprise_memory_live_route_diagnostics_reports_no_call_reason(self):
        from gateway.platforms.api_server import _build_enterprise_memory_live_route_diagnostics

        agent = MagicMock()
        agent.valid_tool_names = set(ENTERPRISE_MEMORY_TOOLS)

        diagnostics = _build_enterprise_memory_live_route_diagnostics(agent, {"messages": []})

        assert diagnostics["enterprise_memory_tools_available"] is True
        assert diagnostics["enterprise_memory_tools_sent_to_model"] is True
        assert diagnostics["enterprise_memory_tool_call_names"] == []
        assert diagnostics["enterprise_memory_tool_no_call_reason"] == (
            "enterprise_memory_tools_available_but_not_called"
        )
