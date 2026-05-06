import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# Replace these with your own paths before running
GARMIN_FETCH_SCRIPT = "REPLACE WITH ABSOLUTE PATH TO garmin_fetch.py"
PYTHON_PATH = "REPLACE WITH PATH TO PYTHON (e.g. /usr/bin/python3 or your venv python)"


class Locallinktest1Capability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}  

    def get_system_prompt(self):
        return (
            "You are a fitness data interpreter for a voice assistant. "
            "Summarize the user's last Garmin activity in 2 sentences, 30 words max. "  
            "Plain spoken English only — no markdown, no bullet points, no symbols. "  
            "Convert meters to miles and seconds to minutes. "
            "Skip null values naturally. "
            "Keep the tone encouraging. "
            "Output goes directly to text-to-speech. "  
            "Example: 'Your last run was about 3 miles in 28 minutes. " 
            "Average heart rate was 155, that is a solid effort.'"
        )

    async def first_function(self):
        user_inquiry = await self.capability_worker.wait_for_complete_transcription()
        await self.capability_worker.speak("Give me a second, pulling up your Garmin stats.")  

        # Validate — speak helpful error if paths have not been configured yet
        if "REPLACE" in GARMIN_FETCH_SCRIPT or "REPLACE" in PYTHON_PATH:
            await self.capability_worker.speak(
                "Garmin is not set up yet. Please update the script path and Python path in main.py."
            )
            self.capability_worker.resume_normal_flow()  
            return

        # Execute garmin_fetch.py on local machine via Local Link
        response = await self.capability_worker.exec_local_command(
            f"{PYTHON_PATH} {GARMIN_FETCH_SCRIPT}",
            timeout=30.0
        )
        self.worker.editor_logging_handler.info(f"[Garmin] Raw response: {response}")

        # Unpack response
        inner = response.get("data") or response if isinstance(response, dict) else {}
        stdout = (inner.get("stdout") or "").strip()
        self.worker.editor_logging_handler.info(f"[Garmin] stdout: {stdout}")

        try:
            garmin_data = json.loads(stdout)
        except Exception as e:
            self.worker.editor_logging_handler.info(f"[Garmin] JSON parse error: {e}")
            await self.capability_worker.speak("I had trouble reading your Garmin data.") 
            self.capability_worker.resume_normal_flow()
            return

        system_prompt = self.get_system_prompt()
        history = []
        history.append({"role": "user", "content": user_inquiry})

        # Now pass the parsed data to the LLM
        result = self.capability_worker.text_to_text_response(
            "Summarize this Garmin health data for the user: %s" % json.dumps(garmin_data),
            history,
            system_prompt,
        )
        if result:
            await self.capability_worker.speak(result)

        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.first_function())
