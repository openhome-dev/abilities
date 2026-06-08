import requests
from datetime import datetime, timezone

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "clinical_trial_data"
CLINICALTRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
CT_HEADERS = {"User-Agent": "OpenHome-ClinicalTrialFinder/1.0"}

POLL_INTERVAL = 604800.0   # 7 days
STARTUP_GRACE = 90         # seconds


def _empty_data() -> dict:
    return {
        "watchlist": [],
        "saved_conditions": [],
        "preferred_location": "",
    }


class ClinicalTrialFinderBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ClinicalTrialsBG] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[ClinicalTrialsBG] Save error: {e!r}")

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _fetch_trial_status(self, nct_id: str) -> str:
        try:
            resp = requests.get(
                f"{CLINICALTRIALS_URL}/{nct_id}",
                params={"format": "json"},
                headers=CT_HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                ps = resp.json().get("protocolSection", {})
                return ps.get("statusModule", {}).get("overallStatus", "")
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[ClinicalTrialsBG] Status fetch error for {nct_id}: {e!r}"
            )
        return ""

    def _count_recruiting_trials(self, condition: str, location: str) -> int:
        try:
            params = {
                "query.cond": condition,
                "filter.overallStatus": "RECRUITING",
                "pageSize": 5,
                "format": "json",
            }
            if location:
                params["query.locn"] = location
            resp = requests.get(CLINICALTRIALS_URL, params=params, headers=CT_HEADERS, timeout=10)
            if resp.status_code == 200:
                return len(resp.json().get("studies", []))
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[ClinicalTrialsBG] Count error for {condition}: {e!r}"
            )
        return 0

    # ------------------------------------------------------------------
    # Daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        self.worker.editor_logging_handler.info("[ClinicalTrialsBG] Daemon started")

        started_at = datetime.now(timezone.utc).timestamp()

        while True:
            try:
                daemon_age = datetime.now(timezone.utc).timestamp() - started_at
                data = self._load_data()

                if daemon_age > STARTUP_GRACE:
                    alerts = []
                    watchlist = data.get("watchlist", [])
                    changed = False

                    for trial in watchlist:
                        new_status = self._fetch_trial_status(trial["nct_id"])
                        if new_status and new_status != trial.get("status", ""):
                            old = trial["status"]
                            trial["status"] = new_status
                            changed = True
                            alerts.append(
                                f"Trial update: {trial['title'][:70]} — "
                                f"status changed from {old} to {new_status}."
                            )
                            self.worker.editor_logging_handler.info(
                                f"[ClinicalTrialsBG] Status change for {trial['nct_id']}: "
                                f"{old} → {new_status}"
                            )

                    if changed:
                        self._save_data(data)

                    location = data.get("preferred_location", "")
                    for condition in data.get("saved_conditions", []):
                        count = self._count_recruiting_trials(condition, location)
                        if count > 0:
                            alerts.append(
                                f"Weekly update: {count} recruiting trial"
                                f"{'s' if count > 1 else ''} currently available for "
                                f"{condition}. Say 'find trials for {condition}' for details."
                            )

                    for msg in alerts:
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(msg)
                        self.worker.editor_logging_handler.info(
                            f"[ClinicalTrialsBG] Alert fired: {msg[:80]}"
                        )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[ClinicalTrialsBG] Loop error: {e!r}")

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
