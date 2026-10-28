"""Devin user-config settings that jail an NPC to the `world` MCP server."""

from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PYTHON = "/opt/homebrew/bin/python3"


def npc_settings() -> dict[str, Any]:
    return {
        "subagents_enabled": False,
        "read_config_from": {
            "agents_standard": False,
            "cursor": False,
            "windsurf": False,
            "claude": False,
            "copilot": False,
            "opencode": False,
            "zed": False,
            "cloud": False,
        },
        "permissions": {
            "allow": ["mcp__world__*"],
            "deny": ["read", "edit", "grep", "glob", "exec"],
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": f"{PYTHON} {HERE / 'jail_hook.py'}", "timeout": 10}],
                }
            ]
        },
    }
