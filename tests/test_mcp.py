"""Tests for the MCP server (stdio JSON-RPC 2.0)."""

from __future__ import annotations

import json

from health_guidance.mcp_server import handle
from tests.conftest import clean_case


def _result(response: dict) -> object:
    assert response["jsonrpc"] == "2.0"
    assert "error" not in response
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def test_initialize_names_the_server() -> None:
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["result"]["serverInfo"]["name"] == "health-guidance-agent"


def test_ping() -> None:
    response = handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert response["result"] == {}


def test_notification_returns_none() -> None:
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_shows_exactly_three_tools() -> None:
    response = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == ["member_data_search", "protocol_check", "guidance_draft"]


def test_call_member_data_search() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "member_data_search", "arguments": {"case": clean_case()}},
        }
    )
    matches = _result(response)
    assert [m["record"]["id"] for m in matches] == ["M001", "M004"]


def test_call_protocol_check() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "protocol_check", "arguments": {"case": clean_case()}},
        }
    )
    check = _result(response)
    assert check["safe"] is True
    assert check["workout"] is not None


def test_call_guidance_draft() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "guidance_draft",
                "arguments": {"case": clean_case(), "member_id": "M001"},
            },
        }
    )
    guidance = _result(response)
    assert guidance["status"] == "draft"
    assert guidance["member_id"] == "M001"


def test_call_unknown_tool_returns_error() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "diagnose", "arguments": {}},
        }
    )
    assert response["error"]["code"] == -32602
    assert "unknown tool" in response["error"]["message"]


def test_call_with_bad_case_returns_error() -> None:
    case_data = clean_case()
    case_data["requester_id"] = "REQ-99"
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "member_data_search", "arguments": {"case": case_data}},
        }
    )
    assert response["error"]["code"] == -32602


def test_unknown_method_returns_error() -> None:
    response = handle({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
    assert response["error"]["code"] == -32601
