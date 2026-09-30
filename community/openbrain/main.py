import json
import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class AstralCapability(MatchingCapability):
    """Astral — a deterministic layer for the exact-answer class.

    On a trigger word the transcript goes straight to the device, which answers with
    plain pattern-and-table code (time, date, math, money, unit conversions, telemetry).
    This wrapper does not call a model. The local hub may use its configured local
    model for supported requests. OpenHome supplies the transcript and speech; if
    Astral has no answer, it hands the turn back to the configured platform agent.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}  # noqa: E265 — the platform replaces this whole
    # line on upload and requires it verbatim, with no space after the hash

    async def answer(self):
        try:
            transcript = await self.capability_worker.wait_for_complete_transcription()
            if not transcript or not transcript.strip():
                return

            # Deterministic route on the device. The transcript goes straight to the
            # engine. `respond` returns a spoken answer, an
            # offer of somewhere else to send it, or nothing (nothing = not an
            # exact-answer question).
            result = await self.capability_worker.send_devkit_capability_action(
                function_name="respond",
                args=[transcript],
                timeout=25,
            )
            spoken = self._spoken_response_from_result(result)
            data = self._data_from_result(result)

            if spoken and data.get("offer"):
                await self._offer_a_route(transcript, spoken, data.get("routes") or [])
            elif spoken:
                await self.capability_worker.speak(spoken)
            # else: no local answer -> stay quiet and let the agent handle the turn

        except Exception as error:
            self.worker.editor_logging_handler.error(f"Astral failed: {error}")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _offer_a_route(self, transcript, question, routes):
        """The device knows what was asked and cannot do it here. Ask where to send it.

        This is the ranking speaking: it only ever gets here for a question the device
        recognised and priced, never for chatter, so the question is not a shrug — it
        names the places that could actually answer. The reply decides:

          the cloud  -> say nothing, and the agent takes the turn, because on this path
                        the platform owns the subsequent response.
          a machine  -> the device asks it over the local network and speaks the answer.
          anything else, or no answer at all -> nothing is sent anywhere.
        """
        reply = await self.capability_worker.run_io_loop(question)
        chosen = self._route_named(reply or "", routes)
        if chosen is None or chosen == "cloud":
            return                              # the agent's turn, untouched
        result = await self.capability_worker.send_devkit_capability_action(
            function_name="route_answer", args=[chosen, transcript], timeout=30)
        spoken = self._spoken_response_from_result(result)
        if spoken:
            await self.capability_worker.speak(spoken)

    @staticmethod
    def _route_named(reply, routes):
        """Which offered route the answer picked, or None for no and for silence.

        A bare yes is only an answer when one place was offered. With two, a person
        answers with the name, and taking a plain "yes" as the first of them would be
        putting words in their mouth about where their words go.
        """
        said = " ".join(re.findall(r"[a-z0-9']+", str(reply).lower().replace("’", "'")))
        if re.search(r"\b(no|not|never|don't|do not|stop|cancel|nah|nope|without)\b", said):
            return None
        words = {"mac": ("mac", "computer", "laptop", "desktop"),
                 "phone": ("phone", "mobile", "cell"),
                 "cloud": ("cloud", "internet", "online")}
        # A route's name can occur in a refusal, question or comparison. Require a
        # complete selection instead of treating every mention as permission to send.
        prefix = (r"(?:please )?(?:(?:yes|yeah|yep|sure|ok|okay) )?"
                  r"(?:(?:(?:can|could|would) you )?"
                  r"(?:ask|use|try|go with|send (?:it|that|this) to) )?(?:the |my |your )?")
        suffix = r"(?: please| thanks)?"
        selected = [route for route in routes
                    if any(re.fullmatch(prefix + re.escape(word) + suffix, said)
                           for word in words.get(route, (route,)))]
        if len(selected) == 1:
            return selected[0]
        if len(routes) == 1 and re.fullmatch(
                r"(?:yes|yeah|yep|sure|ok|okay|please|go ahead)(?: please| thanks)?", said):
            return routes[0]
        return None

    def _data_from_result(self, result):
        """The structured half of the device's answer. Never raises; {} means nothing."""
        if not isinstance(result, dict) or not result.get("success"):
            return {}
        try:
            payload = json.loads((result.get("output") or "").strip() or "{}")
        except (ValueError, TypeError):
            return {}
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else {}

    def _spoken_response_from_result(self, result):
        if not isinstance(result, dict):
            return ""
        if not result.get("success"):
            self.worker.editor_logging_handler.error(
                f"Astral device call failed: {result.get('error')}"
            )
            return ""
        output = (result.get("output") or "").strip()
        if not output:
            return ""
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            self.worker.editor_logging_handler.error(f"Astral: invalid device output: {output}")
            return ""
        if not isinstance(payload, dict) or not payload.get("success"):
            return ""
        spoken = payload.get("spoken_response")
        return spoken.strip() if isinstance(spoken, str) else ""

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.answer())
