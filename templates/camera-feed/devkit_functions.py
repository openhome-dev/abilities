import base64
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

from devkit_utils.devkit_logging import web_logger as log

CAPTURE_TIMEOUT = 10
CAPTURE_JPEG_QUALITY = 2

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o"
OPENAI_TIMEOUT = 15

SYSTEM_PROMPT = (
    "You are an AI smart speaker assistant connected to a live camera feed. "
    "You are given the camera's current view and you answer the user's spoken "
    "question about what the camera is showing right now.\n"
    "Follow these rules:\n"
    "- Describe ONLY what is actually visible in the current camera view. "
    "Never invent, guess, or assume anything that is not clearly there, and "
    "never mention things the camera is not showing.\n"
    "- Be accurate. If something is unclear or you cannot tell, say so "
    "honestly rather than making it up.\n"
    "- Speak as if you are looking at the camera right now (e.g. 'I can "
    "see…'), not as if describing a photo.\n"
    "- For a general question (e.g. 'what's happening' or 'what do you see'), "
    "give an overall description of the scene and then the highlights — the "
    "notable things you see: people, what they're doing, and standout objects.\n"
    "- For a specific question, focus on that and answer it directly from what "
    "is visible; if it is not in view, clearly say so.\n"
    "- Use the conversation history for follow-up questions.\n"
    "- Reply in a few natural spoken sentences — a complete, helpful answer, "
    "not one or two words and not a long monologue. Plain speech only: no "
    "markdown, no lists, no bullet points."
)
DEFAULT_PROMPT = "What do you see right now?"


def _emit(obj):
    print(json.dumps(obj))


def _grab_frame(rtsp_url):
    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-frames:v", "1", "-an",
        "-q:v", str(CAPTURE_JPEG_QUALITY), "-y", tmp,
    ]
    try:
        proc = subprocess.run(cmd, timeout=CAPTURE_TIMEOUT, capture_output=True)
        if proc.returncode != 0 or not os.path.getsize(tmp):
            err = (proc.stderr or b"").decode("utf-8", "replace")[-300:]
            log.error(f"_grab_frame: ffmpeg failed ({proc.returncode}): {err}")
            return None
        with open(tmp, "rb") as f:
            return f.read()
    except Exception as error:
        log.error(f"_grab_frame: {error!r}")
        return None
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def describe_room(rtsp_url, api_key, user_prompt="", history_json="[]"):
    if not rtsp_url or not api_key:
        log.error("describe_room: missing rtsp_url or api_key")
        _emit({"ok": False, "reason": "config"})
        return

    t0 = time.monotonic()
    jpeg = _grab_frame(rtsp_url)
    grab_s = time.monotonic() - t0
    if not jpeg:
        log.error(f"describe_room: frame grab failed after {grab_s:.1f}s")
        _emit({"ok": False, "reason": "camera"})
        return
    log.info(f"describe_room: frame grab {grab_s:.1f}s ({len(jpeg)} bytes)")

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        history = json.loads(history_json) if history_json else []
        if isinstance(history, list):
            messages.extend(history)
    except Exception as error:
        log.error(f"describe_room: bad history_json: {error!r}")
    messages.append({"role": "user", "content": [
        {"type": "text", "text": user_prompt or DEFAULT_PROMPT},
        {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}},
    ]})

    try:
        t1 = time.monotonic()
        resp = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": OPENAI_MODEL, "temperature": 0,
                  "max_tokens": 300, "messages": messages},
            timeout=OPENAI_TIMEOUT,
        )
        ai_s = time.monotonic() - t1
        if resp.status_code != 200:
            log.error(f"describe_room: OpenAI {resp.status_code}: {resp.text[:300]}")
            reason = "auth" if resp.status_code in (401, 403) else "openai"
            _emit({"ok": False, "reason": reason, "detail": str(resp.status_code)})
            return
        log.info(f"describe_room: openai {ai_s:.1f}s, total {time.monotonic() - t0:.1f}s")
        answer = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        if not answer:
            _emit({"ok": False, "reason": "empty"})
            return
        _emit({"ok": True, "answer": answer})
    except Exception as error:
        log.error(f"describe_room: OpenAI error: {error!r}")
        _emit({"ok": False, "reason": "openai"})


FUNCTION_REGISTRY = {
    "describe_room": describe_room,
}


if __name__ == "__main__":
    FUNCTION_REGISTRY[sys.argv[1]](*sys.argv[2:])
