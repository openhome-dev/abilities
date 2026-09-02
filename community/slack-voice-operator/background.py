from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "slack_voice_operator"
POLL_INTERVAL = 600.0
ERROR_SLEEP = 120.0


class SlackMentionMonitor(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        return False

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.background_daemon_mode = background_daemon_mode
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.watch_loop())

    async def watch_loop(self):
        self.capability_worker.resume_normal_flow()
        while True:
            try:
                await self._poll_mentions()
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SlackMonitor] Poll error: {e}")
                await self.worker.session_tasks.sleep(ERROR_SLEEP)
                continue
            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    async def _poll_mentions(self):
        token = self.capability_worker.get_slack_key() or ""
        if not token:
            return

        stored = self.capability_worker.get_single_key(STORAGE_KEY)
        if not stored or not stored.get("slack_user_id"):
            return

        user_id = stored["slack_user_id"]
        watch_channels = stored.get("watch_channels", [])
        last_ts = stored.get("last_mention_ts", "0")
        channel_cache = stored.get("channel_cache", [])

        if not watch_channels:
            return

        slack_client = WebClient(token=token)
        mentions = []

        for ch_id in watch_channels:
            try:
                result = slack_client.conversations_history(
                    channel=ch_id,
                    oldest=last_ts,
                    limit=50,
                )
                for msg in result["messages"]:
                    text = msg.get("text", "")
                    if f"<@{user_id}>" in text:
                        ch_name = next((c["name"] for c in channel_cache if c["id"] == ch_id), ch_id)
                        mentions.append({
                            "channel": ch_name,
                            "text": text,
                            "ts": msg.get("ts", "0"),
                        })
            except SlackApiError as e:
                self.worker.editor_logging_handler.warning(
                    f"[SlackMonitor] history error for {ch_id}: {e.response.get('error', 'unknown')}"
                )
                continue

        if not mentions:
            return

        latest_ts = max(m["ts"] for m in mentions)
        stored["last_mention_ts"] = latest_ts
        try:
            self.capability_worker.update_key(STORAGE_KEY, stored)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SlackMonitor] Timestamp save error: {e!r}")

        mention_text = "\n".join(f"[#{m['channel']}] {m['text']}" for m in mentions)
        urgency = self.capability_worker.text_to_text_response(
            f"Rate the urgency of these Slack @mentions as HIGH, MEDIUM, or LOW. "
            f"HIGH = action needed soon. Return only the label.\n\n{mention_text}"
        ).strip().upper()
        if urgency not in {"HIGH", "MEDIUM", "LOW"}:
            urgency = "MEDIUM"

        count = len(mentions)
        channels_hit = list(dict.fromkeys(m["channel"] for m in mentions))
        channel_str = " and ".join(f"#{c}" for c in channels_hit[:3])

        if urgency == "HIGH":
            spoken = (
                f"Heads up — you have {count} urgent Slack mention{'s' if count != 1 else ''} "
                f"in {channel_str}. Say 'check my Slack' for details."
            )
        else:
            spoken = (
                f"You have {count} new Slack mention{'s' if count != 1 else ''} in {channel_str}. "
                "Say 'check my Slack' whenever you're ready."
            )

        await self.capability_worker.send_interrupt_signal()
        await self.capability_worker.speak(spoken)
