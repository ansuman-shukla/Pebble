"""Claude Code NPC: persona as the whole system prompt, no built-in tools, only the `world` MCP server.

Same surface as AcpAgent (start / new_session / prompt / close) so experiments can swap backends.
One process = one NPC conversation, driven over stream-json stdin/stdout.
"""

import asyncio
import json
import time
from typing import Any

from acp_client import HERE, PYTHON, ROOT, STREAM_LIMIT, RunPaths, Turn

LAUNCHER = ROOT / "backend" / "scripts" / "claude.sh"
PROMPT_TIMEOUT = 600.0
SHUTDOWN_TIMEOUT = 30.0
SESSION = "claude"


class ClaudeNpc:
    def __init__(self, paths: RunPaths, model: str, system_prompt: str):
        self.paths = paths
        self.model = model
        self.system_prompt = system_prompt
        self.process: asyncio.subprocess.Process | None = None
        self.events = paths.events.open("a", encoding="utf-8")

    def log(self, direction: str, message: dict[str, Any]) -> None:
        self.events.write(json.dumps({"t": time.time(), "dir": direction, "msg": message}) + "\n")
        self.events.flush()

    async def start(self) -> None:
        mcp_config = self.paths.root / "claude-mcp.json"
        mcp_config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "world": {"command": PYTHON, "args": [str(HERE / "world_mcp.py"), str(self.paths.world_log)]}
                    }
                }
            )
        )
        self.process = await asyncio.create_subprocess_exec(
            str(LAUNCHER),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--system-prompt",
            self.system_prompt,
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            str(mcp_config),
            "--allowedTools",
            "mcp__world",
            "--no-session-persistence",
            cwd=self.paths.arena,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self.paths.stderr.open("ab"),
            limit=STREAM_LIMIT,
        )

    async def new_session(self) -> str:
        return SESSION

    async def prompt(self, session_id: str, text: str) -> Turn:
        assert self.process and self.process.stdin and self.process.stdout
        message = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.log("out", message)
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()
        turn, started = Turn(), time.monotonic()
        await asyncio.wait_for(self.read_turn(turn), PROMPT_TIMEOUT)
        turn.seconds = time.monotonic() - started
        return turn

    async def read_turn(self, turn: Turn) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            event = json.loads(line)
            self.log("in", event)
            kind = event.get("type")
            if kind == "result":
                turn.stop_reason = event.get("subtype")
                return
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "text" and kind == "assistant":
                    turn.text += block["text"]
                elif block.get("type") == "thinking":
                    turn.thoughts += block.get("thinking", "")
                elif block.get("type") == "tool_use":
                    turn.tool_calls[block["id"]] = {"title": block["name"], "input": block.get("input")}
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in turn.tool_calls:
                    turn.tool_calls[block["tool_use_id"]]["status"] = "failed" if block.get("is_error") else "completed"
        raise RuntimeError("claude exited before finishing the turn")

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            assert self.process.stdin
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), SHUTDOWN_TIMEOUT)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()
        self.events.close()
