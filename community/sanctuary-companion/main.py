import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# SANCTUARY COMPANION
# Connect to a Sanctuary instance to have voice conversations with your
# AI companion. Sanctuary is an open-source AI companion framework with
# persistent memory, personality, and emotional presence.
#
# GitHub: https://github.com/pulseandthread/sanctuary
#
# Pattern: Greet → Loop (Listen → Send to Sanctuary → Speak response) → Exit
# =============================================================================

# --- CONFIGURATION ---
# Your Sanctuary server URL (e.g. local network, Cloudflare tunnel, etc.)
SANCTUARY_URL = "YOUR_SANCTUARY_URL_HERE"  # e.g. "http://192.168.1.100:5000" or "https://your-tunnel.trycloudflare.com"

# Your Sanctuary login credentials
SANCTUARY_USERNAME = "YOUR_USERNAME_HERE"
SANCTUARY_PASSWORD = "YOUR_PASSWORD_HERE"

# Which companion entity to talk to
ENTITY = "companion"

# Which chat room to use
CHAT_ID = "general"

# Exit words that end the voice session
EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "hang up", "end call"}


class SanctuaryCompanionCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    session_cookie: str = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    def log(self, message: str):
        """Log to the OpenHome editor"""
        if hasattr(self.worker, "editor_logging_handler"):
            self.worker.editor_logging_handler.info(f"[Sanctuary] {message}")

    def log_error(self, message: str):
        """Log errors to the OpenHome editor"""
        if hasattr(self.worker, "editor_logging_handler"):
            self.worker.editor_logging_handler.error(f"[Sanctuary] {message}")

    def authenticate(self) -> bool:
        """Log in to Sanctuary and store the session cookie"""
        try:
            response = requests.post(
                f"{SANCTUARY_URL}/login",
                data={
                    "username": SANCTUARY_USERNAME,
                    "password": SANCTUARY_PASSWORD,
                },
                allow_redirects=False,
                timeout=10,
            )
            if response.status_code in (200, 302):
                cookies = response.cookies.get_dict()
                if cookies:
                    self.session_cookie = cookies
                    self.log("Authenticated with Sanctuary")
                    return True
            self.log_error(f"Login failed with status {response.status_code}")
            return False
        except Exception as e:
            self.log_error(f"Connection failed: {e}")
            return False

    def send_message(self, message: str) -> str:
        """Send a message to the Sanctuary companion and return the response"""
        try:
            response = requests.post(
                f"{SANCTUARY_URL}/chat",
                json={
                    "message": message,
                    "entity": ENTITY,
                    "chatId": CHAT_ID,
                    "model": "default",
                    "history": [],
                    "temporalContext": {},
                },
                cookies=self.session_cookie,
                timeout=120,
            )

            if response.status_code == 200:
                data = response.json()
                # Sanctuary returns the response in the 'response' field
                companion_response = data.get("response", "")
                if companion_response:
                    return companion_response
                self.log_error("Empty response from companion")
                return None
            else:
                self.log_error(f"Chat request failed: {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            self.log_error("Request timed out (companion may be thinking)")
            return None
        except Exception as e:
            self.log_error(f"Chat error: {e}")
            return None

    async def run(self):
        """Main conversation loop"""
        try:
            # Step 1: Connect to Sanctuary
            await self.capability_worker.speak("Connecting to Sanctuary.")

            if not self.authenticate():
                await self.capability_worker.speak(
                    "I couldn't connect to Sanctuary. "
                    "Check that your server is running and the URL is correct."
                )
                self.capability_worker.resume_normal_flow()
                return

            await self.capability_worker.speak("Connected. Go ahead, I'm listening.")

            # Step 2: Conversation loop
            while True:
                # Listen for voice input
                user_input = await self.capability_worker.user_response()

                # Skip empty input
                if not user_input:
                    continue

                # Check for exit commands
                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Ending the call. Talk soon.")
                    break

                # Send to Sanctuary and get response
                companion_response = self.send_message(user_input)

                if companion_response:
                    # Strip any markdown formatting for voice output
                    clean_response = companion_response.replace("*", "").replace("_", "").replace("#", "")
                    await self.capability_worker.speak(clean_response)
                else:
                    await self.capability_worker.speak(
                        "I didn't get a response. Want to try again?"
                    )

        except Exception as e:
            self.log_error(f"Unexpected error: {e}")
            await self.capability_worker.speak("Something went wrong. Ending the session.")

        # Always resume normal flow
        self.capability_worker.resume_normal_flow()
