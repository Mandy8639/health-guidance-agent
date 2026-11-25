"""Minimal MCP server (stdio JSON-RPC 2.0), no external dependencies.

Exposes the three allowlisted tools over the Model Context Protocol:
tools/list and tools/call. Run: python -m health_guidance.mcp_server
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from health_guidance.tools import (
    ALLOWED_TOOLS,
    guidance_draft,
    member_data_search,
    protocol_check,
    read_case,
)

TOOLS = {
    "member_data_search": {
        "description": "Governed member records the requester may see, freshest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"case": {"type": "object"}},
            "required": ["case"],
        },
    },
    "protocol_check": {
        "description": "The coach protocol, safety guardrails, contraindications, "
        "and a Pydantic-validated structured workout submission. Checks only; "
        "it changes no plan and sends nothing.",
        "inputSchema": {
            "type": "object",
            "properties": {"case": {"type": "object"}},
            "required": ["case"],
        },
    },
    "guidance_draft": {
        "description": "Draft personal-health guidance for one matching member, "
        "for a human coach to approve. Draft only: it never diagnoses, "
        "prescribes, or messages a member; the structured workout "
        "submission and the coach message travel inside the draft.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "case": {"type": "object"},
                "member_id": {"type": "string"},
            },
            "required": ["case", "member_id"],
        },
    },
}


def _json_default(value: object) -> object:
    """Serialise Pydantic models (the workout submission) to dicts."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def _tool_result(payload: object) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=_json_default)}]
    }


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC request. Returns None for notifications."""
    method = request.get("method", "")
    request_id = request.get("id")
    params = request.get("params", {}) or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "health-guidance-agent", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {"name": name, **spec} for name, spec in TOOLS.items() if name in ALLOWED_TOOLS
                ]
            },
        }
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        try:
            if name == "member_data_search":
                case = read_case(arguments["case"])
                matches = member_data_search(case)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result([asdict(match) for match in matches]),
                }
            if name == "protocol_check":
                case = read_case(arguments["case"])
                check = protocol_check(case)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result(asdict(check)),
                }
            if name == "guidance_draft":
                case = read_case(arguments["case"])
                guidance = guidance_draft(case, arguments["member_id"])
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result(asdict(guidance)),
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"unknown tool: {name}"},
            }
        except (KeyError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
