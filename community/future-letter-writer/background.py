import json
from datetime import datetime
from time import time

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# FUTURE LETTER WRITER — Background Daemon (background.py)
# Checks for letters that have reached their delivery date and
# delivers them by speaking the message aloud.
#
# Coordinates with main.py through shared file: future_letters_data.json
# =============================================================================

LETTERS_FILE = "future_letters_data.json"

# Check every 60 seconds
POLL_INTERVAL = 60.0


class FutureLetterWriterBackground(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    async def background_loop(self):
        self.worker.editor_logging_handler.info(
            "%s: Future Letter Writer daemon started" % time()
        )

        delivered_ids = set()

        while True:
            try:
                # Check if letters file exists
                exists = await self.capability_worker.check_if_file_exists(
                    LETTERS_FILE, False
                )
                if not exists:
                    await self.worker.session_tasks.sleep(POLL_INTERVAL)
                    continue

                # Read letters
                raw = await self.capability_worker.read_file(LETTERS_FILE, False)
                letters = json.loads(raw)

                today = datetime.now().strftime("%Y-%m-%d")
                newly_delivered = set()

                for letter in letters:
                    if letter.get("status") != "pending":
                        continue

                    letter_id = letter.get("id")
                    if not letter_id:
                        # Letters without an id can't be tracked safely;
                        # skip them rather than re-delivering forever.
                        self.worker.editor_logging_handler.error(
                            "[FutureLetterWriter] Skipping letter without id"
                        )
                        continue
                    if letter_id in delivered_ids:
                        continue

                    deliver_date = letter.get("deliver_date", "")
                    if not deliver_date:
                        continue

                    # Check if delivery date has arrived
                    if deliver_date <= today:
                        self.worker.editor_logging_handler.info(
                            f"[FutureLetterWriter] Delivering letter {letter_id}"
                        )

                        # Interrupt and deliver
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            "You left yourself a message. Here it is."
                        )

                        message = letter.get("message", "")
                        created = letter.get("created", "")
                        if created:
                            try:
                                dt = datetime.strptime(created, "%Y-%m-%d %H:%M")
                                date_str = dt.strftime("%B %d")
                                await self.capability_worker.speak(
                                    f"Written on {date_str}, you said:"
                                )
                            except Exception:
                                pass

                        await self.capability_worker.speak(f'"{message}"')
                        await self.capability_worker.speak(
                            "That was a message from your past self."
                        )

                        delivered_ids.add(letter_id)
                        newly_delivered.add(letter_id)

                # Persist delivery status. Re-read the file just before
                # writing and only mutate the delivered entries, so letters
                # recorded via main.py while we were speaking aren't lost.
                if newly_delivered:
                    try:
                        exists = await self.capability_worker.check_if_file_exists(
                            LETTERS_FILE, False
                        )
                        if exists:
                            raw = await self.capability_worker.read_file(
                                LETTERS_FILE, False
                            )
                            letters = json.loads(raw)
                        for letter in letters:
                            if letter.get("id") in newly_delivered:
                                letter["status"] = "delivered"
                                letter["delivered_date"] = today
                        if exists:
                            await self.capability_worker.delete_file(
                                LETTERS_FILE, False
                            )
                        await self.capability_worker.write_file(
                            LETTERS_FILE, json.dumps(letters), False
                        )
                    except Exception as e:
                        self.worker.editor_logging_handler.error(
                            f"[FutureLetterWriter] Save error: {e}"
                        )

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[FutureLetterWriter] Daemon error: {e}"
                )

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.background_loop())
