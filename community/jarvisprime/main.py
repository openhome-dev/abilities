import json
import time
from datetime import datetime, timezone

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

BRAIN_CYCLE_S = 30.0
HEARTBEAT_STALE_S = 90.0
MIN_NEW_MESSAGES = 2
DEFAULT_WATCH_INTERVAL_S = 15

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye",
              "that's all", "never mind", "nevermind", "i'm good", "im good"}

CLASSIFY_SYSTEM = """You route commands for a voice assistant. The text comes
from speech-to-text and may be garbled; infer the most likely intent.
Return ONLY JSON, no fences:
{"intent": "TASK|ANSWER|REMIND|WATCH|RECALL|STATUS|FORGET|CHAT"}
TASK   = research to do in the BACKGROUND ("find out...", "look into...",
         "...and get back to me")
ANSWER = a direct question needing current/live information answered NOW
         (weather, news, prices, sports scores, "what's happening in...")
REMIND = set a reminder or timer ("remind me...", "in 20 minutes tell me...")
WATCH  = monitor something over time ("keep an eye on...", "tell me if/when...",
         "watch my site/the price of...")
RECALL = what am I forgetting / what do you remember / open items
STATUS = what jarvis is doing (watches, tasks)
FORGET = delete a memory, reminder, or watch
CHAT   = anything else. When unsure, CHAT."""

CHAT_SYSTEM = ("You are Jarvis, a concise, proactive voice assistant. "
               "Two sentences max, spoken aloud, no markdown.")


class JarvisCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ---------- lifecycle ----------

    async def run(self):
        try:
            fresh = self.spawn_brain_if_needed()
            await self.capability_worker.speak(
                "At your post." if fresh else "At your service.")
            while True:
                text = await self.capability_worker.user_response()
                if not text or not text.strip():
                    continue
                if text.strip().lower().rstrip(".!?,") in EXIT_WORDS:
                    await self.capability_worker.speak("I'll be here.")
                    break
                if "diagnostic" in text.lower():   # TEMP dev hook — remove before submission
                    await self.speak_diagnostics()
                    continue
                verdict = self.llm_json(text, CLASSIFY_SYSTEM, {"intent": "CHAT"})
                self.log(f"intent={verdict.get('intent')}: {text[:60]}")
                await self.dispatch(verdict.get("intent", "CHAT"), text)
        except Exception as e:
            self.log(f"router crashed: {e}", error=True)
            await self.capability_worker.speak("Something went wrong on my end.")
        finally:
            self.capability_worker.resume_normal_flow()

    def spawn_brain_if_needed(self) -> bool:
        """One brain stem per session. Heartbeat in mj_state guards against
        re-trigger duplicates AND detects a new session (stale beat)."""
        state = self.get("mj_state")
        if time.time() - state.get("beat", 0) < HEARTBEAT_STALE_S:
            return False
        self.worker.session_tasks.create(self.brain_stem())
        self.resume_watches()
        return True

    def resume_watches(self):
        """Re-arm persisted watches on a fresh session. mj_watches survives
        across sessions but the polling tasks are session-scoped and die at
        session end — so every active watch needs its worker re-spawned here.
        Runs only on a fresh brain spawn (stale heartbeat = genuinely new
        session), which is once per session, so it can't double-spawn a watch
        that's already polling within a live session."""
        for job in self.get("mj_watches").get("jobs", []):
            if job.get("active"):
                self.log(f"resuming watch {job['id']}: {job.get('what')}")
                self.worker.session_tasks.create(self.watch_worker(job["id"]))

    async def dispatch(self, intent: str, text: str):
        await {"TASK": self.handle_task, "ANSWER": self.handle_answer,
               "REMIND": self.handle_remind, "WATCH": self.handle_watch,
               "RECALL": self.handle_recall, "STATUS": self.handle_status,
               "FORGET": self.handle_forget,
               }.get(intent, self.handle_chat)(text)

    # ---------- read-only / intake handlers ----------

    async def handle_chat(self, text: str):
        await self.capability_worker.speak(
            self.capability_worker.text_to_text_response(
                text, system_prompt=CHAT_SYSTEM))

    async def handle_recall(self, text: str):
        open_c = [c for c in self.get("mj_memory").get("commitments", [])
                  if not c.get("done")]
        if not open_c:
            await self.capability_worker.speak(
                "Nothing outstanding that I know of.")
            return
        await self.capability_worker.speak(
            self.capability_worker.text_to_text_response(
                json.dumps(open_c[:8]), system_prompt=(
                    "Turn this JSON list of commitments into one or two short "
                    "spoken sentences, most urgent first.")))

    async def handle_status(self, text: str):
        watches = [j for j in self.get("mj_watches").get("jobs", []) if j.get("active")]
        pending = len(self.get("mj_inbox").get("items", []))
        line = f"Watching {len(watches)} thing{'s' if len(watches) != 1 else ''}."
        if pending:
            line += f" {pending} instruction{'s' if pending > 1 else ''} queued."
        await self.capability_worker.speak(line)

    def enqueue(self, item: dict):
        inbox = self.get("mj_inbox", {"items": [], "seq": 0})
        inbox["seq"] += 1
        inbox["items"] = (inbox["items"] + [{**item, "id": inbox["seq"]}])[-20:]
        self.upsert_key("mj_inbox", inbox)

    async def handle_forget(self, text: str):
        self.enqueue({"kind": "forget", "query": text})
        await self.capability_worker.speak(
            "Consider it forgotten — scrubbed from my ledgers momentarily.")

    # ---------- ANSWER: live-info question, answered now ----------

    async def handle_answer(self, text: str):
        await self.capability_worker.speak("Let me check.")
        try:
            answer = self.capability_worker.llm_search(text)
            if not answer or not str(answer).strip():
                raise ValueError("empty search result")
        except Exception as e:
            self.log(f"llm_search failed in ANSWER, falling back: {e}", error=True)
            answer = self.capability_worker.text_to_text_response(
                text, system_prompt=(
                    "Answer concisely from general knowledge; if this needs "
                    "live data, say what you'd check."))
        spoken = self.capability_worker.text_to_text_response(
            str(answer), system_prompt=(
                "Compress to at most two spoken sentences. Lead with the "
                "answer. No markdown, no lists."))
        await self.capability_worker.speak(spoken)

    # ---------- REMIND: timer on the watch machinery ----------

    async def handle_remind(self, text: str):
        now_local = datetime.now().strftime("%A %H:%M")
        parsed = self.llm_json(
            f"Current local time: {now_local}. Request: {text}",
            'Extract a reminder. Return ONLY JSON: {"what": "short reminder '
            'text", "seconds_from_now": <integer seconds until it should '
            'fire>}. If the request gives a clock time, compute seconds from '
            'the current local time given.',
            {"what": None, "seconds_from_now": None})
        what, secs = parsed.get("what"), parsed.get("seconds_from_now")
        if not what or not isinstance(secs, (int, float)) or secs <= 0:
            await self.capability_worker.speak(
                "I couldn't work out when to remind you — try giving me a "
                "time or a delay.")
            return
        secs = int(secs)
        store = self.get("mj_watches", {"jobs": [], "seq": 0})
        store["seq"] = store.get("seq", 0) + 1
        job = {"id": store["seq"], "what": what, "type": "timer",
               "target": None, "threshold": None, "direction": None,
               "fire_at": time.time() + secs,
               "interval_s": max(5, min(15, secs // 4 or 5)), "active": True,
               "last_value": None, "created": self.now_iso()}
        store["jobs"] = (store.get("jobs", []) + [job])[-12:]
        self.upsert_key("mj_watches", store)
        self.worker.session_tasks.create(self.watch_worker(job["id"]))
        mins = secs // 60
        when = (f"in {mins} minute{'s' if mins != 1 else ''}" if mins
                else f"in {secs} seconds")
        await self.capability_worker.speak(f"Set — I'll remind you {when}.")

    # ---------- P1: background task ----------

    async def handle_task(self, text: str):
        parsed = self.llm_json(
            text,
            "Extract a clean, self-contained research question from this "
            'request. Return ONLY JSON: {"question": "...", "label": "a '
            'short 2-4 word topic label"}',
            {"question": text, "label": "that"})
        question = parsed.get("question") or text
        label = parsed.get("label") or "that"
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"I'll look into {label} and get back to you. Sound good?")
        if not confirmed:
            await self.capability_worker.speak("No problem, skipping that.")
            return
        self.worker.session_tasks.create(self.task_worker(question, label))
        await self.capability_worker.speak("On it.")

    async def task_worker(self, question: str, label: str):
        try:
            # Let the router's "On it." finish before the sync LLM calls below
            # block the event loop; llm_search returning in ~2s would otherwise
            # interrupt our own acknowledgement mid-sentence.
            await self.worker.session_tasks.sleep(6)
            try:
                answer = self.capability_worker.llm_search(question)
                if not answer or not str(answer).strip():
                    raise ValueError("empty search result")
            except Exception as e:
                self.log(f"llm_search failed, falling back: {e}", error=True)
                answer = self.capability_worker.text_to_text_response(
                    question, system_prompt=(
                        "Answer concisely from general knowledge; if this "
                        "needs live data, say what you'd check."))
            spoken = self.capability_worker.text_to_text_response(
                str(answer), system_prompt=(
                    "Compress to at most two spoken sentences. Lead with the "
                    "answer. No markdown, no lists."))
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(f"About {label} — {spoken}")
        except Exception as e:
            self.log(f"task_worker crashed: {e}", error=True)
            try:
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"I tried looking into {label} but hit a snag.")
            except Exception:
                pass

    # ---------- P2: watch ----------

    async def handle_watch(self, text: str):
        store = self.get("mj_watches", {"jobs": [], "seq": 0})
        parsed = self.llm_json(
            text,
            'Extract a watch job from this request. Return ONLY JSON: '
            '{"what": "short description", "type": "website|price", '
            '"target": "URL for website, or coingecko id (e.g. bitcoin) for '
            'price", "threshold": <number or null>, '
            '"direction": "above|below|null"}',
            {"what": text, "type": "website", "target": None,
             "threshold": None, "direction": None})
        if not parsed.get("target"):
            await self.capability_worker.speak(
                "I couldn't tell what to watch — try again with a site or a "
                "price to track.")
            return
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"I'll watch {parsed.get('what', text)} and interrupt you when "
            f"something changes. Sound good?")
        if not confirmed:
            await self.capability_worker.speak("No problem, skipping that.")
            return
        store["seq"] = store.get("seq", 0) + 1
        job = {"id": store["seq"], "what": parsed.get("what", text),
               "type": parsed.get("type", "website"), "target": parsed["target"],
               "threshold": parsed.get("threshold"),
               "direction": parsed.get("direction"),
               "interval_s": DEFAULT_WATCH_INTERVAL_S, "active": True,
               "last_value": None, "created": self.now_iso()}
        store["jobs"] = (store.get("jobs", []) + [job])[-12:]
        self.upsert_key("mj_watches", store)
        self.worker.session_tasks.create(self.watch_worker(job["id"]))
        await self.capability_worker.speak("Watching.")

    async def watch_worker(self, job_id: int):
        while True:
            store = self.get("mj_watches", {"jobs": []})
            job = next((j for j in store.get("jobs", []) if j["id"] == job_id), None)
            if not job or not job.get("active"):
                return
            try:
                value = self.poll_watch(job)
            except Exception as e:
                self.log(f"watch {job_id} poll failed: {e}", error=True)
                await self.worker.session_tasks.sleep(job.get("interval_s", DEFAULT_WATCH_INTERVAL_S))
                continue
            fired, msg = self.judge_watch(job, value)
            job["last_value"] = value
            if fired:
                job["active"] = False
            fresh = self.get("mj_watches", {"jobs": []})
            for i, j in enumerate(fresh.get("jobs", [])):
                if j["id"] == job_id:
                    fresh["jobs"][i] = job
            self.upsert_key("mj_watches", fresh)
            if fired:
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(msg)
                return
            await self.worker.session_tasks.sleep(job.get("interval_s", DEFAULT_WATCH_INTERVAL_S))

    @staticmethod
    def poll_watch(job: dict):
        if job["type"] == "timer":
            return time.time()
        if job["type"] == "website":
            try:
                return requests.get(job["target"], timeout=8).status_code
            except Exception:
                return 0
        if job["type"] == "price":
            try:
                resp = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": job["target"], "vs_currencies": "usd"}, timeout=8)
                if resp.status_code != 200:
                    return None
                return float(resp.json()[job["target"]]["usd"])
            except Exception:
                return None  # bad coin id / rate-limit / shape → skip this tick
        return None

    @staticmethod
    def judge_watch(job: dict, value):
        last = job.get("last_value")
        if job["type"] == "timer":
            if value is not None and value >= job.get("fire_at", 0):
                return True, f"Reminder — {job['what']}."
            return False, ""
        if job["type"] == "website":
            if last is None:
                return False, ""
            if last == 200 and value != 200:
                return True, f"Heads up — {job['what']} just went down."
            if last not in (200, None) and value == 200:
                return True, f"Good news — {job['what']} is back up."
            return False, ""
        if job["type"] == "price":
            threshold, direction = job.get("threshold"), job.get("direction")
            if threshold is None or direction is None or last is None or value is None:
                return False, ""  # value None = failed poll → skip, don't crash
            crossed = ((direction == "above" and last < threshold <= value) or
                       (direction == "below" and last > threshold >= value))
            if crossed:
                return True, (f"{job['what']} just crossed {threshold} "
                              f"{direction} — now at {value}.")
            return False, ""
        return False, ""

    async def speak_diagnostics(self):   # TEMP dev hook — remove before submission
        try:
            try:
                self.upsert_key("mj_diag", {"t": int(time.time())})
                kv = "ok" if self.get("mj_diag").get("t") else "broken"
            except Exception as e:
                kv = f"fail {type(e).__name__} {str(e)[:80]}"
            try:
                await self.brain_cycle()
                cyc = "ok"
            except Exception as e:
                cyc = f"fail {type(e).__name__} {str(e)[:120]}"
            state = self.get("mj_state")
            mem = self.get("mj_memory", {"commitments": [], "facts": []})
            beat_age = int(time.time() - state.get("beat", 0))
            await self.capability_worker.speak(
                f"Diagnostics. KV {kv}. Inline cycle {cyc}. "
                f"Cursor {state.get('cursor')}, beat {beat_age} seconds ago. "
                f"Memory {len(mem.get('commitments', []))} commitments, "
                f"{len(mem.get('facts', []))} facts.")
        except Exception as e:
            await self.capability_worker.speak(f"Diagnostics failed: {e}")

    # ---------- brain stem: heartbeat, inbox, memory extraction ----------

    async def brain_stem(self):
        self.log("brain stem online")
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
        await self.drain_inbox()
        await self.extract_cycle(state)

    async def drain_inbox(self):
        inbox = self.get("mj_inbox", {"items": [], "seq": 0})
        items = inbox.get("items", [])
        if not items:
            return
        done_ids = []
        for item in items:
            try:
                if item["kind"] == "forget":
                    await self.brain_forget(item)
                done_ids.append(item["id"])
            except Exception as e:
                self.log(f"inbox item {item.get('id')} failed: {e}", error=True)
                done_ids.append(item["id"])
        fresh = self.get("mj_inbox", {"items": [], "seq": inbox["seq"]})
        fresh["items"] = [i for i in fresh.get("items", []) if i["id"] not in done_ids]
        self.upsert_key("mj_inbox", fresh)

    async def brain_forget(self, item: dict):
        mem = self.get("mj_memory", {"commitments": [], "facts": []})
        verdict = self.llm_json(
            f"Memory: {json.dumps(mem)[:3000]}\nDelete request: {item['query']}",
            system=("Return ONLY JSON: the same memory object with items matching "
                    "the delete request removed. Unchanged if nothing matches."),
            fallback=mem)
        self.upsert_key("mj_memory", verdict)
        await self.write_context_md()

    def extract_system(self, existing: list) -> str:
        known = "\n".join(f'- id {c["id"]}: {c["text"]}'
                          for c in existing[-15:]) or "(none)"
        return f"""You extract durable information from a voice transcript.
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
        verdict = self.llm_json(json.dumps(lines), self.extract_system(mem["commitments"]),
                                {"new_commitments": [], "updates": [], "new_facts": []})
        changed = self.merge_memory(mem, verdict)
        if changed:
            await self.write_context_md()

    def merge_memory(self, mem: dict, verdict: dict) -> bool:
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
        open_c = [c for c in mem["commitments"] if not c.get("done")][-8:]
        facts = mem["facts"][-6:]
        lines = ["## Jarvis memory (auto-maintained)",
                 "Things the user has mentioned; weave them in naturally when "
                 "relevant, especially if asked what they're forgetting."]
        if open_c:
            lines += ["Open commitments:"] + [
                f"- {c['text']}" + (f" (due {c['due']})" if c.get("due") else "")
                for c in open_c]
        if facts:
            lines += ["Context:"] + [f"- {f['text']}" for f in facts]
        await self.replace_file("context.md", "\n".join(lines))

    async def replace_file(self, name: str, content: str):
        if await self.capability_worker.check_if_file_exists(name, in_ability_directory=False):
            await self.capability_worker.delete_file(name, in_ability_directory=False)
        await self.capability_worker.write_file(name, content, in_ability_directory=False)

    # ---------- helpers ----------

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
        """get_single_key returns a wrapper; the stored dict may sit under
        ["value"] directly, as a JSON string, or the result may be the dict
        itself — normalize all three (the SDK doc is vague; discovered live)."""
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
        """The KV API signals failure via {'success': False, ...} return
        values, NOT exceptions (discovered live) — check the response."""
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
        (h.error if error else h.info)(f"[jarvis] {msg}")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
