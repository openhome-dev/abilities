import asyncio
import json
import os
import shlex
import subprocess
from typing import Any

import websockets

OPENHOME_API_KEY = "1812c8e64c9c494f9969e84863bbbd0fbb26a42054acf2b5fd86d3a491d777c9"  # replace with your OpenHome API key


def _json_dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)


def _json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"type": "relay", "data": text}


def _run_command(command: str) -> dict:
    try:
        completed = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": str(exc)}


async def _handle_message(ws: websockets.WebSocketClientProtocol, data: dict) -> None:
    msg_type = data.get("type")
    if msg_type in {"command", "relay"}:
        payload = data.get("data")
        if isinstance(payload, dict):
            command = payload.get("cmd", "")
        else:
            command = str(payload or "")
        if not command:
            return
        result = await asyncio.to_thread(_run_command, command)
        await ws.send(_json_dumps({"type": "response", "data": result}))
        return

    if msg_type == "ping":
        await ws.send(_json_dumps({"type": "pong"}))
        return


async def main() -> None:
    host = "app.openhome.com"
    api_key = os.getenv(
        "LOCAL_LINK_API_KEY",
        OPENHOME_API_KEY,
    )
    if not api_key:
        raise SystemExit("LOCAL_LINK_API_KEY is required")
    client_id = os.getenv("LOCAL_LINK_CLIENT_ID", "laptop")
    role = os.getenv("LOCAL_LINK_ROLE", "agent")

    url = f"wss://{host}/ws/local_link/?api_key={api_key}&client_id={client_id}&role={role}"
    async with websockets.connect(url, max_size=2**20) as ws:
        print(f"connected {url}", flush=True)
        async for message in ws:
            if isinstance(message, bytes):
                continue
            data = _json_loads(message)
            await _handle_message(ws, data)


if __name__ == "__main__":
    asyncio.run(main())
