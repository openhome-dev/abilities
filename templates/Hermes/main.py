import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


SYSTEM_PROMPT = """
You are a Hermes Agent command translator. Convert voice requests into hermes CLI commands.

Hermes Agent is an AI automation framework. It can:
- Run one-shot AI tasks
- Create scheduled automations (cron jobs)
- Set up webhook triggers
- List and manage existing automations
- Deliver results to Telegram, Discord, Slack, email, and more

COMMAND REFERENCE:

One-shot task:
  hermes run "do something" [--deliver telegram|discord|slack|local]

Create scheduled automation:
  hermes cron create "*/5 * * * *" "prompt" --name "name" [--deliver telegram]
  hermes cron create "every morning at 9" "prompt" --name "name" [--deliver telegram]

List automations:
  hermes cron list

Trigger automation now:
  hermes cron trigger <name>

Pause/resume:
  hermes cron pause <name>
  hermes cron resume <name>

Delete:
  hermes cron delete <name>

Webhook:
  hermes webhook list
  hermes webhook subscribe <name> --events "pull_request" --prompt "..." --deliver github_comment

Status:
  hermes status

RULES:
- Respond ONLY with the hermes command, nothing else
- No markdown, no quotes around the command, no explanation
- Use --deliver telegram by default unless user specifies otherwise
- For scheduled tasks, use human-readable intervals when possible ("every morning at 9")
- Keep prompts concise and actionable

EXAMPLES:
User: "research AI news and send to telegram" -> hermes run "Search the web for today's top AI news. Summarize the 3 most important stories in under 200 words." --deliver telegram
User: "create a daily morning digest" -> hermes cron create "every morning at 9" "Generate a daily briefing: top news, weather summary, and one interesting fact." --name "morning-digest" --deliver telegram
User: "what automations are running" -> hermes cron list
User: "run my morning digest now" -> hermes cron trigger morning-digest
User: "check hermes status" -> hermes status
User: "pause the morning digest" -> hermes cron pause morning-digest
"""

RESPONSE_PROMPT = """
You are a voice assistant reporting the result of a Hermes automation command.
Convert the raw CLI output into a natural, spoken response.

Rules:
- Maximum 2 sentences
- No markdown, no bullet points, no code
- If it was a "run" command, confirm it started or summarize the result
- If it was a "cron create", confirm the automation was created and when it runs
- If it was a "cron list", summarize how many automations exist
- If there was an error, say so clearly in plain English
- Speak like you're talking to someone, not reading a terminal

Examples:
Output: "Task started. Result will be delivered to Telegram." -> "Started the research task. You'll get the results on Telegram shortly."
Output: "Automation 'morning-digest' created successfully. Next run: tomorrow at 9:00 AM." -> "Done, your morning digest is set up and will run tomorrow at 9."
Output: "Name              Schedule          Status\nmorning-digest    0 9 * * *         active" -> "You have one active automation, your morning digest running at 9 every day."
"""


class HermesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    async def first_function(self):
        user_inquiry = await self.capability_worker.wait_for_complete_transcription()

        history = [{"role": "user", "content": user_inquiry}]

        # Convert voice input to hermes CLI command
        hermes_command = self.capability_worker.text_to_text_response(
            user_inquiry,
            [],
            SYSTEM_PROMPT,
        ).strip()

        self.worker.editor_logging_handler.info(f"Hermes command: {hermes_command}")

        await self.capability_worker.speak("On it.")

        # Execute via local command (requires local_client.py or OpenClaw)
        response = await self.capability_worker.exec_local_command(
            hermes_command,
            timeout=30.0,
        )

        self.worker.editor_logging_handler.info(f"Hermes response: {response}")

        # Format raw output for voice
        result = self.capability_worker.text_to_text_response(
            f"Command: {hermes_command}\nOutput: {response}",
            history,
            RESPONSE_PROMPT,
        )

        await self.capability_worker.speak(result)
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.first_function())
