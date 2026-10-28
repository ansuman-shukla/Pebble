"""Stub world MCP server (stdio, newline-delimited JSON-RPC). One process per NPC session.

A tiny Stone Age meadow with a few places. Every call is appended to the log given as argv[1].
"""

import json
import sys
import time
from typing import Any

PLACES = {
    "meadow": "Tall grass moves in the wind. Smoke from last night's fire still smells faintly.",
    "river": "Cold, clear water runs over round stones. Fish flash in the shallows.",
    "berry bushes": "Low bushes heavy with dark red berries. Some branches are already stripped.",
    "cave": "A shallow cave under a rock overhang. Ash and old bones on the floor.",
    "hill": "From the hilltop you can see the river bend and, far away, a thin line of smoke.",
}

TOOLS = [
    {
        "name": "look_around",
        "description": "Look at what is around you right now.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "walk_to",
        "description": "Walk to a place you know: meadow, river, berry bushes, cave, hill.",
        "inputSchema": {
            "type": "object",
            "properties": {"place": {"type": "string"}},
            "required": ["place"],
        },
    },
    {
        "name": "eat",
        "description": "Eat something that is within reach.",
        "inputSchema": {
            "type": "object",
            "properties": {"food": {"type": "string"}},
            "required": ["food"],
        },
    },
    {
        "name": "drink",
        "description": "Drink water, if there is water within reach.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "say",
        "description": "Say something out loud. Anyone nearby can hear it.",
        "inputSchema": {
            "type": "object",
            "properties": {"words": {"type": "string"}},
            "required": ["words"],
        },
    },
    {
        "name": "rest",
        "description": "Sit or lie down and rest for a while.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class World:
    def __init__(self) -> None:
        self.place = "meadow"
        self.hunger = 6
        self.thirst = 7

    def body(self) -> str:
        return f"Hunger {self.hunger}/10, thirst {self.thirst}/10."

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name == "look_around":
            return f"You are at the {self.place}. {PLACES[self.place]} {self.body()}"
        if name == "walk_to":
            place = str(args.get("place", "")).lower().strip()
            if place not in PLACES:
                return f"You don't know a place called '{place}'."
            self.place = place
            self.thirst = min(10, self.thirst + 1)
            return f"You walk to the {place}. {PLACES[place]}"
        if name == "eat":
            if self.place != "berry bushes":
                return "There is nothing to eat within reach."
            self.hunger = max(0, self.hunger - 3)
            return f"You eat a handful of berries. They are sour and sweet. {self.body()}"
        if name == "drink":
            if self.place != "river":
                return "There is no water within reach."
            self.thirst = 0
            return f"You kneel and drink the cold water. {self.body()}"
        if name == "say":
            return "Your voice carries over the grass. Nobody answers."
        if name == "rest":
            return "You rest. The sun moves a little across the sky."
        return "Nothing happens."


def main() -> None:
    log_path = sys.argv[1]
    world = World()
    with open(log_path, "a", encoding="utf-8") as log:
        for line in sys.stdin:
            if not line.strip():
                continue
            message = json.loads(line)
            method, msg_id = message.get("method"), message.get("id")
            if msg_id is None:
                continue
            if method == "initialize":
                result: Any = {
                    "protocolVersion": message["params"].get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "world", "version": "0.0.1"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name = message["params"]["name"]
                args = message["params"].get("arguments") or {}
                text = world.call(name, args)
                log.write(json.dumps({"t": time.time(), "tool": name, "args": args, "result": text}) + "\n")
                log.flush()
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            elif method == "ping":
                result = {}
            else:
                reply = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}}
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
                continue
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
