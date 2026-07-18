"""
Off-platform logic tests for jarvisprime/main.py.

Runs the REAL shipping code — it stubs the three platform imports
(`src.agent.capability`, `src.main`, `src.agent.capability_worker`) so main.py
can be imported without OpenHome, then exercises the pure logic that doesn't
need the live platform: the edge-triggered watch judge, the pollers, and the
P1/P2 async handlers against a mocked CapabilityWorker.

Run:  python dev/test_main.py   (needs `requests`; use the CLI venv's python)

This is a dev aid, not part of the pushed ability. It lives in dev/ and
imports main.py from the ability folder one level up.
"""

import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- stub the platform modules main.py imports at top level ---------------
for _name in ("src", "src.agent", "src.agent.capability", "src.main",
              "src.agent.capability_worker"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["src.agent.capability"].MatchingCapability = object
sys.modules["src.main"].AgentWorker = object
sys.modules["src.agent.capability_worker"].CapabilityWorker = object

import main  # noqa: E402  — the real ability
from main import JarvisCapability  # noqa: E402


# --- mocks for the async-handler tests ------------------------------------
class MockSessionTasks:
    def __init__(self):
        self.created = []

    def create(self, coro):
        self.created.append(coro)
        return coro

    async def sleep(self, seconds):
        return None


class MockLogger:
    def info(self, msg):
        pass

    def error(self, msg):
        pass

    def warning(self, msg):
        pass

    def debug(self, msg):
        pass


class MockAgentWorker:
    def __init__(self):
        self.session_tasks = MockSessionTasks()
        self.editor_logging_handler = MockLogger()


class MockCapabilityWorker:
    def __init__(self, *, confirm=True, t2t=None, search=None, kv=None):
        self.spoken = []
        self.interrupts = 0
        self._confirm = confirm
        self._t2t = t2t or (lambda p, **k: "mock")
        self._kv = kv if kv is not None else {}
        if search is not None:
            self.llm_search = search

    async def speak(self, text, file_content=None):
        self.spoken.append(text)

    async def send_interrupt_signal(self):
        self.interrupts += 1

    async def run_confirmation_loop(self, tokens):
        return self._confirm

    def text_to_text_response(self, prompt_text, history=None, system_prompt=""):
        return self._t2t(prompt_text, history=history, system_prompt=system_prompt)

    # key-value store (sync, dict values) — mirrors the SDK contract
    def get_single_key(self, key):
        return self._kv.get(key)

    def create_key(self, key, value):
        self._kv[key] = json.loads(json.dumps(value))

    def update_key(self, key, value):
        self._kv[key] = json.loads(json.dumps(value))


def make_jarvis(**kw):
    j = JarvisCapability()
    j.worker = MockAgentWorker()
    j.capability_worker = MockCapabilityWorker(**kw)
    return j


# --- test harness ----------------------------------------------------------
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ============================ P2 judge ====================================
def test_website_judge():
    print("website judge (edge-triggered):")
    J = JarvisCapability
    site = {"type": "website", "what": "demo site"}

    site["last_value"] = None
    check("first poll baselines (no fire)", J.judge_watch(site, 200) == (False, ""))
    site["last_value"] = 200
    check("200 -> 200 no fire", J.judge_watch(site, 200)[0] is False)
    site["last_value"] = 200
    fired, msg = J.judge_watch(site, 500)
    check("200 -> 500 fires (down)", fired and "went down" in msg)
    site["last_value"] = 200
    check("200 -> 0 unreachable fires", J.judge_watch(site, 0)[0] is True)
    site["last_value"] = 0
    fired, msg = J.judge_watch(site, 200)
    check("0 -> 200 fires (back up)", fired and "back up" in msg)
    site["last_value"] = 500
    check("500 -> 502 no fire (still down)", J.judge_watch(site, 502)[0] is False)


def test_price_judge():
    print("price judge (threshold crossing):")
    J = JarvisCapability
    above = {"type": "price", "what": "bitcoin", "threshold": 100000.0, "direction": "above"}
    above["last_value"] = None
    check("price None last no fire", J.judge_watch(above, 99000.0) == (False, ""))
    above["last_value"] = 99000.0
    fired, msg = J.judge_watch(above, 101000.0)
    check("crosses above fires", fired and "above" in msg)
    above["last_value"] = 101000.0
    check("stays above no re-fire", J.judge_watch(above, 102000.0)[0] is False)

    below = {"type": "price", "what": "eth", "threshold": 2000.0, "direction": "below"}
    below["last_value"] = 2100.0
    fired, msg = J.judge_watch(below, 1900.0)
    check("crosses below fires", fired and "below" in msg)

    noth = {"type": "price", "what": "doge", "threshold": None, "direction": None,
            "last_value": 0.1}
    check("price w/o threshold never fires", J.judge_watch(noth, 0.5)[0] is False)

    # Failed poll (value None) must not crash the comparison, must not fire.
    above["last_value"] = 99000.0
    check("price None value no fire (no crash)", J.judge_watch(above, None) == (False, ""))


# ============================ P2 pollers ==================================
def test_pollers(set_get):
    print("pollers:")
    J = JarvisCapability

    class R:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or {}

        def json(self):
            return self._payload

    set_get(lambda *a, **k: R(200))
    check("website returns status int", J.poll_watch({"type": "website", "target": "http://x"}) == 200)

    def boom(*a, **k):
        raise RuntimeError("no route")
    set_get(boom)
    check("website unreachable -> 0", J.poll_watch({"type": "website", "target": "http://x"}) == 0)

    set_get(lambda *a, **k: R(200, {"bitcoin": {"usd": 12345.6}}))
    check("price returns float", J.poll_watch({"type": "price", "target": "bitcoin"}) == 12345.6)

    set_get(lambda *a, **k: R(429))  # rate-limited
    check("price non-200 -> None", J.poll_watch({"type": "price", "target": "bitcoin"}) is None)
    set_get(lambda *a, **k: R(200, {}))  # missing coin id
    check("price missing id -> None", J.poll_watch({"type": "price", "target": "nope"}) is None)
    set_get(boom)  # network error
    check("price network error -> None", J.poll_watch({"type": "price", "target": "bitcoin"}) is None)


# ============================ P1 handlers =================================
def test_task_worker_uses_search():
    print("task_worker (llm_search present):")
    calls = {"n": 0}

    def search(q):
        calls["n"] += 1
        return "The answer is 42."
    j = make_jarvis(search=search, t2t=lambda p, **k: "Short answer.")
    run(j.task_worker("meaning of life", "life"))
    check("llm_search used", calls["n"] == 1)
    check("interrupt before speak", j.capability_worker.interrupts == 1)
    check("spoke one line about label", j.capability_worker.spoken and
          j.capability_worker.spoken[0].startswith("About life"))


def test_task_worker_fallback():
    print("task_worker (llm_search fails -> fallback):")
    def bad_search(q):
        raise RuntimeError("not wired")
    seen = {"fb": False}

    def t2t(p, **k):
        if "general knowledge" in (k.get("system_prompt") or ""):
            seen["fb"] = True
            return "Fallback answer."
        return "Compressed."
    j = make_jarvis(search=bad_search, t2t=t2t)
    run(j.task_worker("q", "topic"))
    check("fell back to text_to_text_response", seen["fb"])
    check("still interrupted + spoke", j.capability_worker.interrupts == 1 and j.capability_worker.spoken)


def test_task_worker_never_raises():
    print("task_worker (all fails -> must not raise):")
    def bad(*a, **k):
        raise RuntimeError("boom")
    j = make_jarvis(search=bad, t2t=bad)
    try:
        run(j.task_worker("q", "topic"))
        check("swallowed all exceptions", True)
    except Exception as e:
        check(f"swallowed all exceptions (raised {e})", False)


def test_handle_task_confirm():
    print("handle_task (yes -> spawn + 'On it.'):")
    j = make_jarvis(confirm=True, t2t=lambda p, **k: '{"question": "q", "label": "the thing"}')
    run(j.handle_task("find out the thing and get back to me"))
    check("spawned one task", len(j.worker.session_tasks.created) == 1)
    check("said On it.", j.capability_worker.spoken == ["On it."])
    for c in j.worker.session_tasks.created:
        c.close()

    print("handle_task (no -> no spawn):")
    j2 = make_jarvis(confirm=False, t2t=lambda p, **k: '{"question": "q", "label": "x"}')
    run(j2.handle_task("find out x"))
    check("no spawn on decline", len(j2.worker.session_tasks.created) == 0)


# ============================ P2 watch flow ===============================
def test_handle_watch_persists():
    print("handle_watch (persists job with frozen schema):")
    payload = '{"what": "demo site", "type": "website", "target": "http://localhost:8080", "threshold": null, "direction": null}'
    j = make_jarvis(confirm=True, t2t=lambda p, **k: payload)
    run(j.handle_watch("watch my demo site"))
    store = j.capability_worker.get_single_key("mj_watches")
    check("one job persisted", store and len(store.get("jobs", [])) == 1)
    job = store["jobs"][0]
    check("frozen schema keys present", all(k in job for k in (
        "id", "what", "type", "target", "threshold", "direction",
        "interval_s", "active", "last_value", "created")))
    check("active + id 1", job["active"] and job["id"] == 1)
    check("spawned watch_worker", len(j.worker.session_tasks.created) == 1)
    for c in j.worker.session_tasks.created:
        c.close()


def test_watch_worker_one_shot(set_get):
    print("watch_worker (baseline then fire on down, one-shot):")

    class R:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {}

    j = make_jarvis()
    j.capability_worker.create_key("mj_watches", {"jobs": [{
        "id": 1, "what": "demo site", "type": "website",
        "target": "http://localhost:8080", "threshold": None, "direction": None,
        "interval_s": 0, "active": True, "last_value": None, "created": "x"}], "seq": 1})
    seq = iter([200, 500])
    set_get(lambda *a, **k: R(next(seq)))
    run(j.watch_worker(1))
    job = j.capability_worker.get_single_key("mj_watches")["jobs"][0]
    check("deactivated after fire (one-shot)", job["active"] is False)
    check("interrupt fired once", j.capability_worker.interrupts == 1)
    check("spoke down alert", any("went down" in s for s in j.capability_worker.spoken))


def test_watch_worker_forgotten():
    print("watch_worker (inactive job dies quietly):")
    j = make_jarvis()
    j.capability_worker.create_key("mj_watches", {"jobs": [{
        "id": 1, "what": "x", "type": "website", "target": "http://x",
        "threshold": None, "direction": None, "interval_s": 0,
        "active": False, "last_value": None, "created": "x"}], "seq": 1})
    run(j.watch_worker(1))
    check("no interrupt for inactive job", j.capability_worker.interrupts == 0)
    check("no speech for inactive job", j.capability_worker.spoken == [])


def test_resume_watches():
    print("resume_watches (re-arms only active jobs on fresh session):")
    j = make_jarvis()
    j.capability_worker.create_key("mj_watches", {"jobs": [
        {"id": 1, "what": "a", "type": "website", "target": "http://a", "active": True,
         "threshold": None, "direction": None, "interval_s": 15, "last_value": None, "created": "x"},
        {"id": 2, "what": "b", "type": "website", "target": "http://b", "active": False,
         "threshold": None, "direction": None, "interval_s": 15, "last_value": None, "created": "x"},
        {"id": 3, "what": "c", "type": "price", "target": "bitcoin", "active": True,
         "threshold": 100.0, "direction": "above", "interval_s": 15, "last_value": None, "created": "x"},
    ], "seq": 3})
    j.resume_watches()
    check("re-spawned exactly the 2 active jobs (skipped inactive)",
          len(j.worker.session_tasks.created) == 2)
    for c in j.worker.session_tasks.created:
        c.close()

    print("resume_watches (no watches -> no spawns):")
    j2 = make_jarvis()
    j2.resume_watches()
    check("nothing spawned when no watches", len(j2.worker.session_tasks.created) == 0)


def test_spawn_brain_resumes_watches():
    print("spawn_brain_if_needed (stale heartbeat -> brain + watch resume):")
    j = make_jarvis()
    j.capability_worker.create_key("mj_state", {"beat": 0})  # stale
    j.capability_worker.create_key("mj_watches", {"jobs": [
        {"id": 1, "what": "a", "type": "website", "target": "http://a", "active": True,
         "threshold": None, "direction": None, "interval_s": 15, "last_value": None, "created": "x"},
    ], "seq": 1})
    fresh = j.spawn_brain_if_needed()
    check("reported fresh session", fresh is True)
    # 1 brain_stem + 1 watch_worker
    check("spawned brain + 1 watch", len(j.worker.session_tasks.created) == 2)
    for c in j.worker.session_tasks.created:
        c.close()

    print("spawn_brain_if_needed (live heartbeat -> no respawn):")
    import time as _t
    j2 = make_jarvis()
    j2.capability_worker.create_key("mj_state", {"beat": _t.time()})  # fresh beat
    j2.capability_worker.create_key("mj_watches", {"jobs": [
        {"id": 1, "what": "a", "type": "website", "target": "http://a", "active": True,
         "threshold": None, "direction": None, "interval_s": 15, "last_value": None, "created": "x"},
    ], "seq": 1})
    fresh2 = j2.spawn_brain_if_needed()
    check("reported not-fresh", fresh2 is False)
    check("no respawn within live session", len(j2.worker.session_tasks.created) == 0)


# --- requests.get monkeypatch on the main module --------------------------
def make_set_get():
    original = main.requests.get

    def setter(fn):
        main.requests.get = fn

    def restore():
        main.requests.get = original
    return setter, restore


if __name__ == "__main__":
    setter, restore = make_set_get()
    try:
        test_website_judge()
        test_price_judge()
        test_pollers(setter)
        test_task_worker_uses_search()
        test_task_worker_fallback()
        test_task_worker_never_raises()
        test_handle_task_confirm()
        test_handle_watch_persists()
        test_watch_worker_one_shot(setter)
        test_watch_worker_forgotten()
        test_resume_watches()
        test_spawn_brain_resumes_watches()
    finally:
        restore()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if passed == total else 1)
