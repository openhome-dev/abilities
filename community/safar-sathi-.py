import json
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class SafarSathiCapability(MatchingCapability):
    """
    SafarSathi — voice-facing Interactive Skill.

    Three key moments:
      1. ENTRY  — warm, immediate, reassuring greeting.
      2. ACTIVE — parallel task speaks calming phrases every 15 s.
      3. EXIT   — gentle, affirming goodbye when user says they are safe.

    Location + camera stream are sent once by background.py on activation.
    No audio recording in this version.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    async def _read_state(self) -> dict:
        filename = "safar_sathi_state.json"
        try:
            if not await self.capability_worker.check_if_file_exists(filename, False):
                seed_data = {
                    "alert_active": False,
                    "mode": "passive",
                    "gps_feed_url": "",
                    "use_openclaw_storage": False
                }
                if await self.capability_worker.check_if_file_exists(filename, True):
                    raw_seed = await self.capability_worker.read_file(filename, True)
                    if raw_seed:
                        try:
                            seed_data = json.loads(raw_seed)
                        except Exception:
                            pass
                await self._write_state(seed_data)
                return seed_data
            raw = await self.capability_worker.read_file(filename, False)
            if not (raw or "").strip():
                return {}
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SafarSathi] State read error: {e}")
            return {}

    async def _write_state(self, state: dict):
        filename = "safar_sathi_state.json"
        try:
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
            await self.capability_worker.write_file(
                filename, json.dumps(state, ensure_ascii=False, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SafarSathi] State write error: {e}")

    async def run(self):
        mode = "active"
        try:
            # ---------------------------------------------------------- #
            # STEP 1 — Capture trigger utterance
            # ---------------------------------------------------------- #
            full_input = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[SafarSathi] Triggered by: '{full_input}'")

            # ---------------------------------------------------------- #
            # STEP 2 — Classify ACTIVE vs PASSIVE (duress) mode
            # ---------------------------------------------------------- #
            passive_triggers = [
                "everything is fine", "turning off lights",
                "going to sleep", "quiet mode",
            ]
            mode = "passive" if any(p in full_input.lower() for p in passive_triggers) else "active"
            self.worker.editor_logging_handler.info(f"[SafarSathi] Mode: {mode.upper()}")

            # ---------------------------------------------------------- #
            # STEP 3 — Write alert state so background.py fires
            # ---------------------------------------------------------- #
            state = await self._read_state()
            state["alert_active"] = True
            state["mode"] = mode
            await self._write_state(state)
            self.worker.editor_logging_handler.info("[SafarSathi] Alert state written — background will now send location + camera stream.")

            # ---------------------------------------------------------- #
            # STEP 4 — ENTRY: warm greeting
            # ---------------------------------------------------------- #
            if mode == "active":
                await self.capability_worker.speak(
                    "I'm here with you. Safar Sathi is now active. "
                    "I've sent your location and live camera stream to your emergency contact. "
                    "You are not alone. Stay calm and stay safe. "
                    "Say 'I am safe now' when you want me to stop."
                )

            # ---------------------------------------------------------- #
            # STEP 5 — Parallel calming task (fires every 15 seconds)
            # ---------------------------------------------------------- #
            keep_speaking = [True]

            calming_phrases = [
                "I'm still right here with you. Stay calm, your contact is watching.",
                "You are doing so well. Keep breathing slowly. Help is on the way.",
                "Safar Sathi is with you every second. You are not alone.",
                "Your live camera stream has been shared. Someone is watching over you.",
                "You are strong. I am here. Focus on your breath — in and out.",
                "Your emergency contact has been alerted. Hold on, help is coming.",
                "I've got you. Just keep going. Everything is going to be okay.",
            ]

            async def _reassurance_loop():
                idx = 0
                while keep_speaking[0]:
                    await self.worker.session_tasks.sleep(15.0)
                    if not keep_speaking[0]:
                        break
                    if mode == "active":
                        await self.capability_worker.speak(
                            calming_phrases[idx % len(calming_phrases)]
                        )
                        idx += 1

            if mode == "active":
                self.worker.session_tasks.create(_reassurance_loop())

            # ---------------------------------------------------------- #
            # STEP 6 — Deactivation listening loop
            # ---------------------------------------------------------- #
            active_deactivation_phrases = [
                "i'm safe now", "im safe now", "i am safe now",
                "safe now", "cancel", "stop safar"
            ]
            passive_deactivation_phrases = [
                "cancel alert", "deactivate alert", "stop alarm"
            ]

            while True:
                user_input = await self.capability_worker.wait_for_complete_transcription()
                if not user_input:
                    continue

                text = user_input.lower().strip()
                self.worker.editor_logging_handler.info(f"[SafarSathi] Heard: '{text}'")

                deactivated = False
                if mode == "active" and any(p in text for p in active_deactivation_phrases):
                    deactivated = True
                elif mode == "passive" and any(p in text for p in passive_deactivation_phrases):
                    deactivated = True

                if deactivated:
                    # -------------------------------------------------- #
                    # STEP 7 — EXIT: warm goodbye
                    # -------------------------------------------------- #
                    keep_speaking[0] = False

                    state = await self._read_state()
                    state["alert_active"] = False
                    await self._write_state(state)
                    self.worker.editor_logging_handler.info("[SafarSathi] Alert deactivated.")

                    if mode == "active":
                        await self.capability_worker.speak(
                            "I'm so relieved you are safe. "
                            "Safar Sathi is now turning off. "
                            "Your contact will receive a message that you are okay. "
                            "Take care of yourself. I'm always here if you need me."
                        )
                    else:
                        self.worker.editor_logging_handler.info(
                            "[SafarSathi] Passive deactivation — silent exit."
                        )
                    break

                # Any other speech — acknowledge and keep going
                if mode == "active":
                    await self.capability_worker.speak(
                        "I heard you. I'm still here. Stay calm — help is on the way."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SafarSathi] Runtime error: {e}")
            try:
                state = await self._read_state()
                state["alert_active"] = False
                await self._write_state(state)
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.editor_logging_handler.info("[SafarSathi] Interactive Skill initialised.")
        self.worker.session_tasks.create(self.run())
