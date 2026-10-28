"""Minimal ACP client that drives Pebble's private `ds acp` bridge (jailed Devin natives) for NPCs.

The jail itself lives in each Pebble account's Devin config (backend/scripts/apply_npc_config.py).
Every JSON-RPC message in and out is written to the run's events.jsonl.
"""

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LAUNCHER = ROOT / "backend" / "scripts" / "ds.sh"
RUNTIME = ROOT / ".runtime"
PYTHON = "/opt/homebrew/bin/python3"
REQUEST_TIMEOUT = 120.0
PROMPT_TIMEOUT = 600.0
SHUTDOWN_TIMEOUT = 30.0
STREAM_LIMIT = 16 * 1024 * 1024


@dataclass(frozen=True)
class RunPaths:
    root: Path
    arena: Path
    events: Path
    jail_log: Path
    world_log: Path
    stderr: Path


def prepare_run(name: str) -> RunPaths:
    root = RUNTIME / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    arena = root / "arena"
    arena.mkdir(parents=True)
    # Own git root so Devin's rule/hook discovery stops here instead of climbing into Pebble.
    subprocess.run(["git", "init", "-q", str(arena)], check=True)
    return RunPaths(
        root=root,
        arena=arena,
        events=root / "events.jsonl",
        jail_log=root / "jail.jsonl",
        world_log=root / "world.jsonl",
        stderr=root / "ds-stderr.log",
    )


@dataclass
class Turn:
    text: str = ""
    thoughts: str = ""
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    permission_requests: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    seconds: float = 0.0


class AcpAgent:
    def __init__(self, paths: RunPaths, model: str | None = None):
        self.paths = paths
        self.model = model
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        self.turns: dict[str, Turn] = {}
        self.reader: asyncio.Task | None = None
        self.events = paths.events.open("a", encoding="utf-8")

    def log(self, direction: str, message: dict[str, Any]) -> None:
        self.events.write(json.dumps({"t": time.time(), "dir": direction, "msg": message}) + "\n")
        self.events.flush()

    async def start(self) -> dict[str, Any]:
        self.process = await asyncio.create_subprocess_exec(
            str(LAUNCHER),
            "acp",
            cwd=self.paths.arena,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=self.paths.stderr.open("ab"),
            limit=STREAM_LIMIT,
        )
        self.reader = asyncio.create_task(self.read_loop())
        init = await self.request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "clientInfo": {"name": "pebble", "version": "0.0.1"},
            },
        )
        # No `authenticate` call: the ACP server falls back to the isolated runtime's stored login.
        return init

    async def send(self, message: dict[str, Any]) -> None:
        assert self.process and self.process.stdin
        self.log("out", message)
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> Any:
        self.next_id += 1
        msg_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[msg_id] = future
        await self.send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        return await asyncio.wait_for(future, timeout)

    async def read_loop(self) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            if not line.strip():
                continue
            message = json.loads(line)
            self.log("in", message)
            if "method" in message:
                await self.on_agent_message(message)
            elif (future := self.pending.pop(message.get("id"), None)) and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(f"ACP error: {message['error']}"))
                else:
                    future.set_result(message.get("result"))
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError("devin acp exited"))

    async def on_agent_message(self, message: dict[str, Any]) -> None:
        method, params, msg_id = message["method"], message.get("params") or {}, message.get("id")
        if method == "session/update":
            self.on_update(params.get("sessionId", ""), params.get("update") or {})
        if msg_id is None:
            return
        if method == "session/request_permission":
            turn = self.turns.setdefault(params.get("sessionId", ""), Turn())
            turn.permission_requests.append(params)
            reject = next(
                (o["optionId"] for o in params.get("options", []) if str(o.get("kind", "")).startswith("reject")),
                None,
            )
            outcome = {"outcome": "selected", "optionId": reject} if reject else {"outcome": "cancelled"}
            await self.send({"jsonrpc": "2.0", "id": msg_id, "result": {"outcome": outcome}})
            return
        await self.send(
            {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"{method} not supported"}}
        )

    def on_update(self, session_id: str, update: dict[str, Any]) -> None:
        turn = self.turns.setdefault(session_id, Turn())
        kind = update.get("sessionUpdate")
        content = update.get("content")
        if kind == "agent_message_chunk" and isinstance(content, dict):
            turn.text += content.get("text", "")
        elif kind == "agent_thought_chunk" and isinstance(content, dict):
            turn.thoughts += content.get("text", "")
        elif kind in ("tool_call", "tool_call_update"):
            call = turn.tool_calls.setdefault(update.get("toolCallId", "?"), {})
            call.update({k: v for k, v in update.items() if k not in ("sessionUpdate", "toolCallId")})

    async def new_session(self) -> str:
        result = await self.request(
            "session/new",
            {
                "cwd": str(self.paths.arena),
                "mcpServers": [
                    {
                        "name": "world",
                        "command": PYTHON,
                        "args": [str(HERE / "world_mcp.py"), str(self.paths.world_log)],
                        "env": [],
                    }
                ],
            },
        )
        session_id = result["sessionId"]
        if self.model:
            await self.set_config(session_id, "model", self.resolve_model(result))
        return session_id

    def resolve_model(self, session: dict[str, Any]) -> str:
        """Match `self.model` (e.g. 'sonnet', 'gpt-6.1-luna') against the session's model choices."""
        assert self.model
        options = next(o for o in session.get("configOptions", []) if o["id"] == "model")["options"]
        wanted = self.model.lower()
        exact = [o["value"] for o in options if o["value"].lower() == wanted]
        fuzzy = [o["value"] for o in options if wanted in o["value"].lower() or wanted in o.get("name", "").lower()]
        if not (exact or fuzzy):
            raise ValueError(f"Model {self.model!r} not offered; choices: {[o['value'] for o in options]}")
        return (exact or fuzzy)[0]

    async def set_config(self, session_id: str, config_id: str, value: str) -> Any:
        return await self.request(
            "session/set_config_option", {"sessionId": session_id, "configId": config_id, "value": value}
        )

    async def prompt(self, session_id: str, text: str) -> Turn:
        turn = self.turns[session_id] = Turn()
        started = time.monotonic()
        result = await self.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            PROMPT_TIMEOUT,
        )
        turn.stop_reason = (result or {}).get("stopReason")
        turn.seconds = time.monotonic() - started
        return turn

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            assert self.process.stdin
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), SHUTDOWN_TIMEOUT)
            except TimeoutError:
                self.process.terminate()
                await self.process.wait()
        if self.reader:
            await self.reader
        self.events.close()
