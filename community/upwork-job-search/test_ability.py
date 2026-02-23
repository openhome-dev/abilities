#!/usr/bin/env python3
"""
Automated tests for the Upwork Job Search ability (Remotive API backend).
Covers: imports, _clean_html, search_jobs (live API), format_job_for_speech.
"""
from main import UpworkJobSearchCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []


def report(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    results.append(passed)


def make_capability() -> UpworkJobSearchCapability:
    worker = AgentWorker()
    cap = UpworkJobSearchCapability.register_capability()
    cap.worker = worker
    cap.capability_worker = CapabilityWorker(worker)
    return cap


# ─────────────────────────────────────────────
# TEST 1 — Module imports correctly
# ─────────────────────────────────────────────
def test_import():
    print("\n[1] Module import")
    try:
        cap = make_capability()
        report("UpworkJobSearchCapability instantiated", cap is not None)
        report("unique_name loaded from config.json", bool(cap.unique_name))
        report(
            "matching_hotwords is a non-empty list",
            isinstance(cap.matching_hotwords, list) and len(cap.matching_hotwords) > 0,
        )
    except Exception as e:
        report("import / instantiation", False, str(e))


# ─────────────────────────────────────────────
# TEST 2 — _clean_html
# ─────────────────────────────────────────────
def test_clean_html():
    print("\n[2] _clean_html()")
    cap = make_capability()

    cases = [
        ("<b>Hello</b> world", "Hello world"),
        ("<p>Line 1</p><p>Line 2</p>", "Line 1 Line 2"),
        ("<br>New line", "New line"),
        ("No tags here", "No tags here"),
        ("A &amp; B &lt;3&gt;", "A & B <3>"),
        ("&nbsp;spaced&nbsp;", "spaced"),
        ('<a href="x">link</a>', "link"),
        ("", ""),
        ("<ul><li>item 1</li><li>item 2</li></ul>", "item 1 item 2"),
    ]

    for raw, expected in cases:
        result = cap._clean_html(raw)
        passed = result == expected
        report(f"_clean_html({raw!r})", passed, f"got {result!r}" if not passed else "")


# ─────────────────────────────────────────────
# TEST 3 — format_job_for_speech
# ─────────────────────────────────────────────
def test_format_job_for_speech():
    print("\n[3] format_job_for_speech()")
    cap = make_capability()

    job = {
        "title": "Python Developer",
        "company": "Acme Corp",
        "description": "Build REST APIs using FastAPI and PostgreSQL.",
        "link": "https://remotive.com/job/123",
        "pub_date": "2024-01-01T00:00:00",
        "salary": "$80k - $120k",
        "location": "Worldwide",
        "job_type": "full_time",
    }

    speech = cap.format_job_for_speech(job, 0)
    report("returns a string", isinstance(speech, str))
    report("contains job index (Job 1)", "Job 1" in speech)
    report("contains title", "Python Developer" in speech)
    report("contains company name", "Acme Corp" in speech)
    report("contains location", "Worldwide" in speech)
    report("contains salary", "$80k" in speech)
    report("contains description snippet", "FastAPI" in speech)
    report("not empty", bool(speech.strip()))

    # No salary case
    job_no_salary = {**job, "salary": "Not specified"}
    speech2 = cap.format_job_for_speech(job_no_salary, 1)
    report("omits salary line when not specified", "Salary:" not in speech2)
    report("still contains title when no salary", "Python Developer" in speech2)


# ─────────────────────────────────────────────
# TEST 4 — search_jobs live API call
# ─────────────────────────────────────────────
async def test_search_jobs():
    print("\n[4] search_jobs() — live Remotive API call")
    cap = make_capability()

    jobs = await cap.search_jobs("software engineer")

    report("returns a list (not None)", jobs is not None, "" if jobs else "got None — check network")

    if jobs is None:
        report("skipping further job checks (no results)", False)
        return

    report("returns at most 5 jobs", len(jobs) <= 5, f"got {len(jobs)}")
    report("returns at least 1 job", len(jobs) >= 1, f"got {len(jobs)}")

    job = jobs[0]
    required_keys = ["title", "company", "description", "link", "pub_date", "salary", "location"]
    for key in required_keys:
        report(f"first job has '{key}' key", key in job)

    report("title is a non-empty string", isinstance(job["title"], str) and bool(job["title"]))
    report("description has no raw HTML tags", "<" not in job["description"])
    report(
        "description truncated to <=303 chars",
        len(job["description"]) <= 303,
        f"len={len(job['description'])}",
    )
    report(
        "link starts with https://",
        job["link"].startswith("https://"),
        f"got {job['link'][:60]}",
    )

    print("\n  Sample job fetched:")
    print(f"    Title    : {job['title']}")
    print(f"    Company  : {job['company']}")
    print(f"    Location : {job['location']}")
    print(f"    Salary   : {job['salary']}")
    print(f"    Published: {job['pub_date']}")
    print(f"    Desc     : {job['description'][:120]}...")
    print(f"    Link     : {job['link']}")


# ─────────────────────────────────────────────
# TEST 5 — search_jobs edge cases
# ─────────────────────────────────────────────
async def test_edge_cases():
    print("\n[5] search_jobs() — edge cases")
    cap = make_capability()

    # A nonsense query — should return None or an empty-list-derived None, not crash
    jobs = await cap.search_jobs("zzzzzzzzzzzzz_no_results_expected_xyzxyz")
    report(
        "nonsense query returns None or list (no crash)",
        jobs is None or isinstance(jobs, list),
    )

    # Empty string — should not crash
    jobs_empty = await cap.search_jobs("")
    report(
        "empty query returns None or list (no crash)",
        jobs_empty is None or isinstance(jobs_empty, list),
    )

    # Multi-word phrase that triggers the keyword fallback
    jobs_fallback = await cap.search_jobs("python developer")
    report(
        "multi-word fallback returns None or list (no crash)",
        jobs_fallback is None or isinstance(jobs_fallback, list),
    )
    if jobs_fallback:
        report(
            "fallback result has 'title' key",
            "title" in jobs_fallback[0],
        )


# ─────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────
async def run_all():
    print("=" * 60)
    print("  Upwork Job Search — Ability Test Suite")
    print("=" * 60)

    test_import()
    test_clean_html()
    test_format_job_for_speech()
    await test_search_jobs()
    await test_edge_cases()

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  Results: {passed}/{total} passed  — ALL TESTS PASSED")
    else:
        print(f"  Results: {passed}/{total} passed  ({failed} FAILED)")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(run_all())
