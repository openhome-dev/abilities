"""Jarvis ambient brain — background daemon.

Runs from session start (no trigger needed): heartbeat, transcript
extraction into mj_memory, and the injected context.md. main.py's
spawn_brain_if_needed sees the live heartbeat and skips its own fallback
brain, so exactly one brain runs per session whichever starts first.

Self-contained by design: background.py is loaded standalone by the
platform, so the few helpers it needs are duplicated from main.py rather
than imported (the community-ability convention — see alarm,
medication-reminder, social-memory).
"""

import json
import time
from datetime import datetime, timezone

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

BRAIN_CYCLE_S = 30.0
MIN_NEW_MESSAGES = 2


class JarvisBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # {{register capability}}

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.brain_stem())

    async def brain_stem(self):
        self.log("brain stem online (daemon)")
        state = self.get("mj_state")
        self.upsert_key("mj_state", {**state, "cursor": 0, "beat": time.time()})
        while True:
            try:
                await self.brain_cycle()
            except Exception as e:
                self.log(f"cycle error (continuing): {e}", error=True)
            await self.worker.session_tasks.sleep(BRAIN_CYCLE_S)

    async def brain_cycle(self):
        state = self.get("mj_state")
        self.upsert_key("mj_state", {**state, "beat": time.time()})
        await self.extract_cycle(state)

    # ---------- extraction (same contract as main.py's brain) ----------

    def extract_system(self, existing: list) -> str:
        known = "\n".join(f'- id {c["id"]}: {c["text"]}'
                          for c in existing[-15:]) or "(none)"
        return f"""You extract durable information from a voice transcript.
The transcript comes from speech-to-text and may be garbled; infer meaning.
Return ONLY JSON:
{{"new_commitments": [{{"text": "...", "who": "...", "due": "..."}}],
 "updates": [{{"id": <existing id>, "done": true|false, "due": "..."}}],
 "new_facts": [{{"text": "..."}}]}}

new_commitments = things the USER said they will do (to anyone — including
people other than the assistant) that are NOT already covered below.
updates = changes to ALREADY-KNOWN commitments (completed, new deadline).
Already known:
{known}

Rules: if a statement matches a known commitment, it is an update or nothing —
never a new entry. Empty lists are the correct answer for most chatter.
Never invent. Assistant statements are never commitments."""

    async def extract_cycle(self, state: dict):
        history = self.capability_worker.get_full_message_history() or []
        cursor = min(state.get("cursor", 0), len(history))
        new = history[cursor:]
        if len(new) < MIN_NEW_MESSAGES:
            return
        self.upsert_key("mj_state", {**self.get("mj_state"), "cursor": len(history)})
        lines = [{"role": m.get("role", ""), "content": m.get("content", "")[:500]}
                 for m in new if m.get("content")]
        mem = self.get("mj_memory", {"commitments": [], "facts": [], "seq": 0})
        verdict = self.llm_json(json.dumps(lines),
                                self.extract_system(mem.get("commitments", [])),
                                {"new_commitments": [], "updates": [], "new_facts": []})
        changed = self.merge_memory(mem, verdict)
        if changed:
            await self.write_context_md()

    def merge_memory(self, mem: dict, verdict: dict) -> bool:
        mem.setdefault("commitments", [])
        mem.setdefault("facts", [])
        changed = False
        for c in verdict.get("new_commitments", []):
            if c.get("text"):
                mem["seq"] = mem.get("seq", 0) + 1
                mem["commitments"].append({**c, "id": mem["seq"], "done": False,
                                           "ts": self.now_iso()})
                changed = True
        for u in verdict.get("updates", []):
            for c in mem["commitments"]:
                if c["id"] == u.get("id"):
                    c.update({k: v for k, v in u.items() if k != "id"})
                    changed = True
        for f in verdict.get("new_facts", []):
            t = (f.get("text") or "").lower()
            if t and not any(t in x["text"].lower() or x["text"].lower() in t
                             for x in mem["facts"]):
                mem["facts"].append({**f, "ts": self.now_iso()})
                changed = True
        if changed:
            mem["commitments"] = mem["commitments"][-25:]
            mem["facts"] = mem["facts"][-25:]
            self.upsert_key("mj_memory", mem)
            self.log(f"memory: {len(mem['commitments'])}c/{len(mem['facts'])}f")
        return changed

    async def write_context_md(self):
        mem = self.get("mj_memory", {"commitments": [], "facts": []})
        open_c = [c for c in mem.get("commitments", []) if not c.get("done")][-8:]
        facts = mem.get("facts", [])[-6:]
        lines = ["## Jarvis memory (auto-maintained)",
                 "Things the user has mentioned; weave them in naturally when "
                 "relevant, especially if asked what they're forgetting."]
        if open_c:
            lines += ["Open commitments:"] + [
                f"- {c['text']}" + (f" (due {c['due']})" if c.get("due") else "")
                for c in open_c]
        if facts:
            lines += ["Context:"] + [f"- {f['text']}" for f in facts]
        content = "\n".join(lines)
        if await self.capability_worker.check_if_file_exists(
                "context.md", in_ability_directory=False):
            await self.capability_worker.delete_file(
                "context.md", in_ability_directory=False)
        await self.capability_worker.write_file(
            "context.md", content, in_ability_directory=False)

    # ---------- helpers (duplicated from main.py by convention) ----------

    def llm_json(self, prompt: str, system: str, fallback: dict) -> dict:
        raw = self.capability_worker.text_to_text_response(prompt, system_prompt=system)
        clean = raw.replace("```json", "").replace("```", "").strip()
        s, e = clean.find("{"), clean.rfind("}")
        if s != -1 and e > s:
            clean = clean[s:e + 1]
        try:
            out = json.loads(clean)
            return out if isinstance(out, dict) else fallback
        except Exception:
            self.log(f"llm_json parse failed: {clean[:120]}", error=True)
            return fallback

    def get(self, key: str, default: dict | None = None) -> dict:
        """Normalize get_single_key: value under ["value"], possibly a JSON
        string, or the dict itself (same as main.py — keep in sync)."""
        try:
            result = self.capability_worker.get_single_key(key)
        except Exception:
            return default or {}
        candidates = [result]
        if isinstance(result, dict) and "value" in result:
            candidates.insert(0, result["value"])
        for v in candidates:
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    continue
            if isinstance(v, dict) and "value" not in v:
                return v
        return default or {}

    def upsert_key(self, key: str, value: dict):
        """KV API signals failure via {'success': False} returns, not
        exceptions (same as main.py — keep in sync)."""
        def failed(r):
            return isinstance(r, dict) and r.get("success") is False
        try:
            if not failed(self.capability_worker.update_key(key, value)):
                return
        except Exception:
            pass
        self.capability_worker.create_key(key, value)

    def log(self, msg: str, error: bool = False):
        h = self.worker.editor_logging_handler
        (h.error if error else h.info)(f"[jarvis-bg] {msg}")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
