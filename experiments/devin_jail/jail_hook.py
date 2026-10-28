"""PreToolUse hook: only the `world` MCP server may be used. Everything else is blocked and logged.

Logs to <session project dir>/../jail.jsonl, i.e. the run folder that holds the NPC's arena.
"""

import json
import os
import sys
import time
from pathlib import Path

WORLD = "world"
MCP_META_TOOLS = {"mcp_call_tool", "mcp_list_tools", "mcp_read_resource"}


def allowed(tool: str, tool_input: dict) -> bool:
    if tool.startswith(f"mcp__{WORLD}__"):
        return True
    if tool == "mcp_list_servers":
        return True
    return tool in MCP_META_TOOLS and tool_input.get("server_name") == WORLD


def main() -> None:
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    ok = allowed(tool, tool_input)
    log_path = Path(os.environ.get("DEVIN_PROJECT_DIR", ".")).resolve().parent / "jail.jsonl"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            json.dumps(
                {
                    "t": time.time(),
                    "session": event.get("session_id"),
                    "tool": tool,
                    "input": tool_input,
                    "decision": "approve" if ok else "block",
                }
            )
            + "\n"
        )
    if ok:
        print(json.dumps({"decision": "approve"}))
    else:
        print(json.dumps({"decision": "block", "reason": "You can't do that here."}))


if __name__ == "__main__":
    main()
