import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# OBSIDIAN NOTES
# Voice-controlled Obsidian vault access. Search, read, and create notes
# through a REST API bridge (Obsidian Local REST API plugin or custom endpoint).
#
# Setup: Install the "Local REST API" Obsidian plugin, or deploy your own
# bridge endpoint. Set OBSIDIAN_API_URL and OBSIDIAN_API_KEY below.
#
# Pattern: Greet → Ask intent → Route to search/read/create → Loop or Exit
# =============================================================================

# --- CONFIGURATION ---
# Option 1: Obsidian Local REST API plugin (https://github.com/coddingtonbear/obsidian-local-rest-api)
#   URL: https://localhost:27124 (default)
#   Key: Set in plugin settings
# Option 2: Custom bridge API (e.g. Vercel serverless function synced to vault)
OBSIDIAN_API_URL = os.environ.get("OBSIDIAN_API_URL", "https://localhost:27124")
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "leave", "nevermind"}


class ObsidianNotesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def api_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if OBSIDIAN_API_KEY:
            headers["Authorization"] = f"Bearer {OBSIDIAN_API_KEY}"
        return headers

    async def search_notes(self, query: str) -> list[dict] | None:
        """Search the vault for notes matching query."""
        try:
            resp = requests.post(
                f"{OBSIDIAN_API_URL}/search/simple/",
                headers=self.api_headers(),
                json={"query": query},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json()
                return results[:5]  # Top 5 results
            else:
                self.worker.editor_logging_handler.error(
                    f"[Obsidian] Search failed: {resp.status_code}"
                )
                return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Obsidian] Search error: {e}")
            return None

    async def read_note(self, path: str) -> str | None:
        """Read a specific note by path."""
        try:
            resp = requests.get(
                f"{OBSIDIAN_API_URL}/vault/{path}",
                headers={**self.api_headers(), "Accept": "text/markdown"},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Obsidian] Read error: {e}")
            return None

    async def create_note(self, title: str, content: str) -> bool:
        """Create a new note in the vault."""
        try:
            path = f"Voice Notes/{title}.md"
            resp = requests.put(
                f"{OBSIDIAN_API_URL}/vault/{path}",
                headers={**self.api_headers(), "Content-Type": "text/markdown"},
                data=content,
                verify=False,
                timeout=10,
            )
            return resp.status_code in (200, 201, 204)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Obsidian] Create error: {e}")
            return False

    async def run(self):
        await self.capability_worker.speak(
            "Obsidian vault ready. I can search your notes, read a specific note, "
            "or save a new voice note. What would you like?"
        )

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input:
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak("Closing the vault. See you later!")
                break

            # Use LLM to classify intent
            intent = self.capability_worker.text_to_text_response(
                f"Classify this user request into exactly one word: 'search', 'read', or 'create'. "
                f"User said: '{user_input}'. Respond with only the one word."
            ).strip().lower()

            if "search" in intent:
                await self.handle_search(user_input)
            elif "create" in intent or "save" in intent or "note" in intent:
                await self.handle_create(user_input)
            elif "read" in intent:
                await self.handle_read(user_input)
            else:
                # Default to search
                await self.handle_search(user_input)

            await self.capability_worker.speak(
                "Anything else? Search, read, save a note, or say stop."
            )

        self.capability_worker.resume_normal_flow()

    async def handle_search(self, query: str):
        await self.capability_worker.speak(f"Searching your vault...")
        results = await self.search_notes(query)

        if results is None:
            await self.capability_worker.speak(
                "I couldn't connect to your Obsidian vault. "
                "Make sure the Local REST API plugin is running."
            )
            return

        if not results:
            await self.capability_worker.speak(
                f"No notes found matching that. Try different keywords?"
            )
            return

        # Summarize results via LLM
        titles = [r.get("filename", r.get("path", "Untitled")) for r in results]
        summary = self.capability_worker.text_to_text_response(
            f"The user searched their Obsidian vault and found these notes: {', '.join(titles)}. "
            f"List them briefly in a natural spoken format. Keep it short."
        )
        await self.capability_worker.speak(summary)
        await self.capability_worker.speak("Want me to read any of these?")

    async def handle_read(self, user_input: str):
        # Extract note name from input
        note_name = self.capability_worker.text_to_text_response(
            f"Extract just the note title or filename from this request: '{user_input}'. "
            f"Return only the title, nothing else."
        ).strip()

        await self.capability_worker.speak(f"Reading {note_name}...")
        content = await self.read_note(f"{note_name}.md")

        if content is None:
            # Try without .md
            content = await self.read_note(note_name)

        if content is None:
            await self.capability_worker.speak(
                f"Couldn't find a note called {note_name}. Try searching for it instead?"
            )
            return

        # Summarize long notes for voice
        if len(content) > 500:
            summary = self.capability_worker.text_to_text_response(
                f"Summarize this Obsidian note in 2-3 spoken sentences: {content[:2000]}"
            )
            await self.capability_worker.speak(summary)
        else:
            await self.capability_worker.speak(content)

    async def handle_create(self, user_input: str):
        await self.capability_worker.speak("What should the note be called?")
        title = await self.capability_worker.user_response()

        if any(word in title.lower() for word in EXIT_WORDS):
            return

        await self.capability_worker.speak("Got it. Now tell me what to write.")
        content = await self.capability_worker.user_response()

        if any(word in content.lower() for word in EXIT_WORDS):
            return

        # Format the note content
        formatted = f"# {title}\n\n{content}\n\n---\n*Created via voice with ARI*\n"
        success = await self.create_note(title, formatted)

        if success:
            await self.capability_worker.speak(f"Saved! Your note '{title}' is in the Voice Notes folder.")
        else:
            await self.capability_worker.speak(
                "Couldn't save the note. Check that the Obsidian REST API is running."
            )
