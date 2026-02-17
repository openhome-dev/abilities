import json
import os

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# OBSIDIAN NOTES
# Voice-controlled Obsidian vault access via a Vercel API proxy backed by
# a GitHub-synced vault. Search, read, create notes, and pull active context
# (long-term memory) through the proxy.
#
# Setup: Set OBSIDIAN_VAULT_API to your Vercel deployment URL + /api/vault
#   Default: https://ari-avatar-remote.vercel.app/api/vault
#
# The Vercel endpoint proxies to a private GitHub repo containing the vault.
# Vault changes auto-commit and push via obsidian-commit.sh hook.
#
# Pattern: Greet → Ask intent → Route to search/read/create/recall → Loop or Exit
# =============================================================================

VAULT_API = os.environ.get(
    "OBSIDIAN_VAULT_API",
    "https://ari-avatar-remote.vercel.app/api/vault"
)

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

    def vault_request(self, payload: dict) -> dict | None:
        """Make a request to the Vercel vault API."""
        try:
            resp = requests.post(VAULT_API, json=payload, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            self.worker.editor_logging_handler.error(
                f"[Obsidian] API error {resp.status_code}: {resp.text[:200]}"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Obsidian] Request error: {e}")
            return None

    async def run(self):
        await self.capability_worker.speak(
            "Obsidian vault connected. I can search your notes, read a specific note, "
            "save a new voice note, or recall your current context and priorities. "
            "What would you like?"
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
                f"Classify this user request into exactly one word: "
                f"'search', 'read', 'create', or 'context'. "
                f"'context' means the user wants to know current priorities, focus, or memory. "
                f"User said: '{user_input}'. Respond with only the one word."
            ).strip().lower()

            if "context" in intent or "memor" in intent or "priorit" in intent:
                await self.handle_context()
            elif "search" in intent:
                await self.handle_search(user_input)
            elif "create" in intent or "save" in intent or "note" in intent:
                await self.handle_create(user_input)
            elif "read" in intent:
                await self.handle_read(user_input)
            else:
                await self.handle_search(user_input)

            await self.capability_worker.speak(
                "Anything else? Search, read, save a note, check context, or say stop."
            )

        self.capability_worker.resume_normal_flow()

    async def handle_context(self):
        """Read active-context.md — ARI's long-term memory and current focus."""
        await self.capability_worker.speak("Pulling up your active context...")
        data = self.vault_request({"action": "context"})

        if data is None or "content" not in data:
            await self.capability_worker.speak(
                "Couldn't reach the vault. The sync might be down."
            )
            return

        # Summarize context for voice
        summary = self.capability_worker.text_to_text_response(
            f"Summarize this active context document in 3-4 spoken sentences. "
            f"Focus on current priorities, active projects, and recent learnings:\n\n"
            f"{data['content'][:3000]}"
        )
        await self.capability_worker.speak(summary)

    async def handle_search(self, query: str):
        await self.capability_worker.speak("Searching your vault...")

        # Extract search terms from natural language
        search_query = self.capability_worker.text_to_text_response(
            f"Extract the key search terms from this request: '{query}'. "
            f"Return only the search keywords, nothing else."
        ).strip()

        data = self.vault_request({"action": "search", "query": search_query})

        if data is None:
            await self.capability_worker.speak(
                "Couldn't connect to the vault. Check your setup."
            )
            return

        results = data.get("results", [])
        if not results:
            await self.capability_worker.speak(
                "No notes found matching that. Try different keywords?"
            )
            return

        # Summarize results via LLM
        titles = [r.get("name", r.get("path", "Untitled")) for r in results]
        summary = self.capability_worker.text_to_text_response(
            f"The user searched their Obsidian vault and found these notes: "
            f"{', '.join(titles)}. List them briefly in a natural spoken format."
        )
        await self.capability_worker.speak(summary)
        await self.capability_worker.speak("Want me to read any of these?")

    async def handle_read(self, user_input: str):
        # Extract note name from input
        note_name = self.capability_worker.text_to_text_response(
            f"Extract just the note title or filename from this request: '{user_input}'. "
            f"Return only the title, nothing else."
        ).strip()

        await self.capability_worker.speak(f"Looking for {note_name}...")

        # Try to find the note by searching first
        data = self.vault_request({"action": "search", "query": note_name})
        if data and data.get("results"):
            # Read the first matching result
            note_path = data["results"][0]["path"]
            read_data = self.vault_request({"action": "read", "path": note_path})
        else:
            # Try direct path guesses
            read_data = self.vault_request({"action": "read", "path": f"{note_name}.md"})
            if not read_data or "content" not in read_data:
                read_data = self.vault_request({"action": "read", "path": note_name})

        if not read_data or "content" not in read_data:
            await self.capability_worker.speak(
                f"Couldn't find a note called {note_name}. Try searching for it?"
            )
            return

        content = read_data["content"]
        # Summarize long notes for voice
        if len(content) > 500:
            summary = self.capability_worker.text_to_text_response(
                f"Summarize this Obsidian note in 2-3 spoken sentences:\n\n{content[:3000]}"
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
        data = self.vault_request({
            "action": "save",
            "title": title,
            "content": formatted,
            "folder": "inbox"
        })

        if data and data.get("saved"):
            await self.capability_worker.speak(
                f"Saved! Your note '{title}' is in the inbox folder."
            )
        else:
            await self.capability_worker.speak(
                "Couldn't save the note. The vault sync might be down."
            )
