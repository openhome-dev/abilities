from typing import ClassVar, Set
import json
import os
import time
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class VoiceMemoryCaptureCapability(MatchingCapability):
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

    FILE_NAME: ClassVar[str] = "voice_memory_entries.json"
    MAX_ENTRIES: ClassVar[int] = 100

    EXIT_WORDS: ClassVar[Set[str]] = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "never mind"}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        """Main logic when the ability is triggered."""
        try:
            # Safely get the trigger text from history
            history = self.worker.agent_memory.full_message_history
            trigger_text = ""
            if history:
                last_msg = history[-1]
                if isinstance(last_msg, dict):
                    trigger_text = last_msg.get("content", "")
                elif hasattr(last_msg, 'content'):
                    trigger_text = last_msg.content
                else:
                    trigger_text = str(last_msg)

            lower_text = trigger_text.lower().strip()

            # Determine mode based on keywords (reliable fallback)
            mode = "save"
            content = trigger_text
            query = trigger_text

            if any(kw in lower_text for kw in ["forget", "delete", "remove", "erase", "clear", "get rid of"]):
                mode = "delete"
                query = trigger_text
            elif any(kw in lower_text for kw in [
                "list", "lists", "list my", "list all", "list everything", "list the things", "list of",
                "show all", "show my", "recap", "recap my", "recap of", "summarize", "summarize my",
                "summary", "give me a summary", "quick summary", "full summary", "memory recap",
                "how many memories", "count my", "how many do I have", "what memories do I have",
                "overview of", "tell me about my memories", "my memories recap"
            ]):
                mode = "list"
            elif any(kw in lower_text for kw in [
                "what did I save", "what do I have", "do I have anything", "what did I remember",
                "find my note", "search my memories", "what do I have on"
            ]):
                mode = "recall"
                query = trigger_text

            if mode == "save":
                await self.handle_save(content)
            elif mode == "recall":
                await self.handle_recall(query)
            elif mode == "delete":
                await self.handle_delete(query)
            elif mode == "list":
                await self.handle_list()
            else:
                await self.capability_worker.speak("Not sure what you want. Try 'remember that...' to save or 'what did I save about...' to recall.")

        except Exception as e:
            await self.capability_worker.speak("Something went wrong with memory. Try again?")
            if hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.warning(f"Memory error: {str(e)}")

        finally:
            self.capability_worker.resume_normal_flow()

    async def handle_save(self, content: str):
        if not content.strip():
            await self.capability_worker.speak("What would you like me to remember?")
            content = await self.capability_worker.user_response()
            if not content.strip():
                await self.capability_worker.speak("Nothing to save. Exiting.")
                return

        await self.capability_worker.speak("One sec... saving.")

        classify_prompt = """You are a memory classifier. Extract the core fact from the user's voice input. Return ONLY valid JSON, no markdown fences.

{
  "summary": "clean one-sentence summary of what to remember",
  "category": "idea | reminder | person | place | thing | note",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}

Examples:
Input: 'remember that sarahs birthday is june 12th'
Output: {"summary": "Sarah's birthday is June 12th", "category": "person", "keywords": ["sarah", "birthday", "june"]}

Input: 'dont let me forget we need more dog food'
Output: {"summary": "Need to buy more dog food", "category": "reminder", "keywords": ["dog food", "buy", "groceries"]}"""

        raw = self.capability_worker.text_to_text_response(classify_prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(raw)
        except:
            parsed = {"summary": content, "category": "note", "keywords": []}

        entry = {
            "id": str(int(time.time())),
            "timestamp": datetime.now().isoformat(),
            "raw_input": content,
            "summary": parsed["summary"],
            "category": parsed["category"],
            "keywords": parsed["keywords"]
        }

        memories = []
        if await self.capability_worker.check_if_file_exists(self.FILE_NAME, temp=False):
            raw_file = await self.capability_worker.read_file(self.FILE_NAME, temp=False)
            memories = json.loads(raw_file)

        if len(memories) >= self.MAX_ENTRIES:
            await self.capability_worker.speak(
                f"Your memory is full at {self.MAX_ENTRIES} entries. "
                "Want me to read the oldest ones so you can decide what to remove?"
            )
            return

        memories.append(entry)

        await self.capability_worker.delete_file(self.FILE_NAME, temp=False)
        await self.capability_worker.write_file(self.FILE_NAME, json.dumps(memories), temp=False)

        await self.capability_worker.speak(f"Got it. I saved: {parsed['summary']}")

        await self.capability_worker.speak("Anything else to save?")
        more = await self.capability_worker.user_response()
        if more.strip() and not any(w in more.lower() for w in self.EXIT_WORDS):
            await self.handle_save(more)

    async def handle_recall(self, query: str):
        if not query.strip():
            await self.capability_worker.speak("What topic are you looking for?")
            query = await self.capability_worker.user_response()
            if not query.strip():
                await self.capability_worker.speak("No topic given. Exiting.")
                return

        await self.capability_worker.speak("One sec... checking memories.")

        memories = []
        if await self.capability_worker.check_if_file_exists(self.FILE_NAME, temp=False):
            raw = await self.capability_worker.read_file(self.FILE_NAME, temp=False)
            memories = json.loads(raw)
        else:
            await self.capability_worker.speak("You don't have any saved memories yet. Say 'remember that' to start saving.")
            return

        if not memories:
            await self.capability_worker.speak("No memories saved yet.")
            return

        current_time = datetime.now()
        enriched_memories = []
        for m in memories:
            try:
                ts = datetime.fromisoformat(m["timestamp"])
                days_ago = (current_time - ts).days
                m["days_ago"] = days_ago
            except:
                m["days_ago"] = 0
            enriched_memories.append(m)

        recall_prompt = f"""You are a memory retrieval assistant. The user has saved memories over time. 
Given their query and the list of saved memories, return the top 3 most relevant matches as JSON.

Return ONLY valid JSON, no markdown fences:
[
  {{"id": "...", "summary": "...", "days_ago": number}},
  ...
]

If nothing matches, return an empty array: []

MEMORIES: {json.dumps(enriched_memories)}
QUERY: {query}"""

        raw = self.capability_worker.text_to_text_response(recall_prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            matches = json.loads(raw)
        except:
            matches = []

        if not matches:
            await self.capability_worker.speak("I didn't find anything about that. Want to try a different search?")
        else:
            response = "I found these: "
            for m in matches[:3]:
                days = m.get("days_ago", 0)
                day_str = f"{days} day{'s' if days != 1 else ''} ago" if days >= 0 else "recently"
                response += f"{day_str} you saved: {m['summary']}. "
            await self.capability_worker.speak(response)

        await self.capability_worker.speak("Want to search for something else?")
        more = await self.capability_worker.user_response()
        if more.strip() and not any(w in more.lower() for w in self.EXIT_WORDS):
            await self.handle_recall(more)

    async def handle_delete(self, query: str):
        await self.capability_worker.speak("One sec... looking for that memory.")

        memories = []
        if await self.capability_worker.check_if_file_exists(self.FILE_NAME, temp=False):
            raw = await self.capability_worker.read_file(self.FILE_NAME, temp=False)
            memories = json.loads(raw)
        else:
            await self.capability_worker.speak("No memories saved yet. Nothing to delete.")
            return

        if not memories:
            await self.capability_worker.speak("No memories saved yet.")
            return

        delete_prompt = f"""You are a memory deletion assistant.
From the saved memories, find the entry that best matches the user's delete request.
Return ONLY the ID of the entry to delete (as a string), or "none" if no match.

MEMORIES: {json.dumps(memories)}
DELETE REQUEST: {query}"""

        raw = self.capability_worker.text_to_text_response(delete_prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()
        target_id = raw.strip()

        if target_id == "none" or not target_id or target_id not in [e["id"] for e in memories]:
            await self.capability_worker.speak("I couldn't find a matching memory to delete. Try describing it exactly (e.g. 'delete my wife's birthday').")
            return

        entry = next((e for e in memories if e["id"] == target_id), None)
        if not entry:
            await self.capability_worker.speak("Couldn't find that memory.")
            return

        await self.capability_worker.speak(f"Delete '{entry['summary']}'? Say yes to confirm.")

        confirm = await self.capability_worker.user_response()
        if "yes" in confirm.lower():
            memories = [e for e in memories if e["id"] != target_id]
            await self.capability_worker.delete_file(self.FILE_NAME, temp=False)
            await self.capability_worker.write_file(self.FILE_NAME, json.dumps(memories), temp=False)
            await self.capability_worker.speak(f"Deleted '{entry['summary']}'. Gone now.")
        else:
            await self.capability_worker.speak("Delete cancelled.")

    async def handle_list(self):
        await self.capability_worker.speak("One sec... counting your memories.")

        memories = []
        if await self.capability_worker.check_if_file_exists(self.FILE_NAME, temp=False):
            raw = await self.capability_worker.read_file(self.FILE_NAME, temp=False)
            memories = json.loads(raw)
        else:
            await self.capability_worker.speak("You don't have any saved memories yet.")
            return

        if not memories:
            await self.capability_worker.speak("No memories saved yet.")
            return

        count = len(memories)
        categories = {}
        for m in memories:
            cat = m.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        summary = f"You have {count} saved memories. "
        if categories:
            parts = []
            for cat, num in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                parts.append(f"{num} {cat}{'s' if num != 1 else ''}")
            summary += ", ".join(parts) + ". "
        else:
            summary += "No categories yet. "

        summary += "Want me to go through them?"

        await self.capability_worker.speak(summary)

        await self.capability_worker.speak("Say 'yes' or a category (like 'reminders' or 'people') to hear more, or 'stop' to exit.")
        more = await self.capability_worker.user_response()
        if more.strip() and not any(w in more.lower() for w in self.EXIT_WORDS):
            await self.capability_worker.speak("Going deeper coming soon. For now, try specific recall like 'what did I save about [topic]'.")
        else:
            await self.capability_worker.speak("Okay, done listing.")
