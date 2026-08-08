import json

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

RTSP_URL_1 = "rtsp://<user>:<pass>@<camera-ip>:554/<stream-path>"
RTSP_URL_2 = "rtsp://<user>:<pass>@<camera-ip>:554/<stream-path>"
OPENAI_API_KEY = "sk-REPLACE_WITH_YOUR_OPENAI_KEY"

DEVICE_TIMEOUT = 15
HISTORY_MAX = 40

ERROR_MESSAGES = {
    "camera": "I can't reach that camera right now — it may be offline, or the "
              "address might be wrong.",
    "openai": "I got the picture, but the vision service couldn't process it "
              "just now. Please try again in a moment.",
    "auth": "The OpenAI key looks invalid — please check it in the settings.",
    "config": "The camera or the OpenAI key isn't set up yet.",
    "empty": "I looked, but couldn't make out anything clear in that view.",
}
DEVICE_DOWN_MESSAGE = "I couldn't reach the camera device just now. Please try again."
GENERIC_ERROR = "Something went wrong with that request."

INTENT_PROMPT = (
    "You interpret a single user message sent to a voice assistant that "
    "can look at two cameras and describe what they show. Decide three things "
    "and reply with ONLY a JSON object — no extra text, no markdown — using "
    "these exact fields:\n"
    '- "intent": "exit" if the user wants to stop or end the conversation '
    '(for example: "stop", "that\'s all", "I\'m done", "goodbye", "never mind", '
    '"cancel", "thanks bye"). Otherwise "ask".\n'
    '- "camera": "camera_2" if the user refers to the second, other, or next '
    'camera. Otherwise "camera_1" (the default camera).\n'
    '- "ack": a short, natural spoken line (max 10 words) that says you are '
    "looking for the specific thing the user asked about, in the camera view. "
    'Phrase it like "Looking for plants in the camera" or "Checking the camera '
    'for people" — tied to what they asked. Acknowledge only; do not answer '
    "the question. For an exit, a short sign-off.\n\n"
    "Examples:\n"
    'Message: "what is happening"\n'
    '{{"intent": "ask", "camera": "camera_1", "ack": "Looking at what the camera sees"}}\n'
    'Message: "how many plants are in the picture"\n'
    '{{"intent": "ask", "camera": "camera_1", "ack": "Looking for plants in the camera"}}\n'
    'Message: "how many people are standing"\n'
    '{{"intent": "ask", "camera": "camera_1", "ack": "Looking for people in the camera"}}\n'
    'Message: "what is on the other camera"\n'
    '{{"intent": "ask", "camera": "camera_2", "ack": "Checking the other camera now"}}\n'
    'Message: "switch to the second camera, anyone at the door"\n'
    '{{"intent": "ask", "camera": "camera_2", "ack": "Checking the second camera for anyone"}}\n'
    'Message: "what is written on the wall"\n'
    '{{"intent": "ask", "camera": "camera_1", "ack": "Looking for writing on the wall"}}\n'
    'Message: "okay that is all, thanks"\n'
    '{{"intent": "exit", "camera": "camera_1", "ack": "Okay, all done"}}\n'
    'Message: "stop"\n'
    '{{"intent": "exit", "camera": "camera_1", "ack": "Stopping now"}}\n\n'
    "Now classify this message:\n"
    "Message: {text}"
)


class CameraFeedCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        history = []
        try:
            question = await self.capability_worker.wait_for_complete_transcription()

            while True:
                if not question or not question.strip():
                    break

                is_exit, cam, ack = self._classify(question)
                if is_exit:
                    break

                url = RTSP_URL_2 if cam == 2 else RTSP_URL_1
                labeled = f"[Camera {cam}] {question.strip()}"

                await self.capability_worker.speak(ack)

                result = await self.capability_worker.send_devkit_capability_action(
                    "describe_room",
                    [url, OPENAI_API_KEY, labeled, json.dumps(history)],
                    DEVICE_TIMEOUT,
                )
                ok, message = self._read_result(result)
                await self.capability_worker.speak(message)

                if ok:
                    history.append({"role": "user", "content": labeled})
                    history.append({"role": "assistant", "content": message})
                    history[:] = history[-HISTORY_MAX:]

                question = await self.capability_worker.user_response()

            await self.capability_worker.speak("Okay, done watching. Talk soon.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CameraRoomWatch] {e!r}")
            await self.capability_worker.speak("Something went wrong checking the camera.")
        finally:
            self.capability_worker.resume_normal_flow()

    def _read_result(self, result):
        if not isinstance(result, dict) or not result.get("success"):
            return False, DEVICE_DOWN_MESSAGE
        out = (result.get("output") or "").strip()
        try:
            data = json.loads(out)
        except Exception:
            return (bool(out), out or GENERIC_ERROR)
        if data.get("ok"):
            answer = (data.get("answer") or "").strip()
            return (True, answer) if answer else (False, ERROR_MESSAGES["empty"])
        reason = str(data.get("reason", ""))
        return False, ERROR_MESSAGES.get(reason, GENERIC_ERROR)

    def _classify(self, text: str):
        filler = "Let me take a look, one moment."
        try:
            raw = self.capability_worker.text_to_text_response(
                INTENT_PROMPT.format(text=text)
            )
            clean = (raw or "").replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            is_exit = str(data.get("intent", "")).lower() == "exit"
            camera = 2 if str(data.get("camera", "")).lower() == "camera_2" else 1
            ack = str(data.get("ack", "")).strip() or filler
            return is_exit, camera, ack
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CameraRoomWatch] intent parse: {e!r}")
            return False, 1, filler
