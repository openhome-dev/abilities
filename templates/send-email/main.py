import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class SendemailhCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    # Do not change following tag of register capability
    #{{register capability}}

    async def email_sender(self):

        # ── Hardcoded config ──────────────────────────────────────
        HOST            = "smtp.gmail.com"
        PORT            = 465                        # SSL
        SENDER_EMAIL    = "test@gmail.com"
        SENDER_PASSWORD = "test 1234 5678 9121" # Gmail app password
        RECEIVER_EMAIL  = "receiver_test@gmail.com"
        SUBJECT         = "Test Email"
        BODY            = "Hello! This is a test email sent from the EmailSendingCapability."
        ATTACHMENTS     = ["testfile.txt"]           # Just the file name, path is resolved internally
        # ─────────────────────────────────────────────────────────

        status = self.capability_worker.send_email(
            host=HOST,
            port=PORT,
            sender_email=SENDER_EMAIL,
            sender_password=SENDER_PASSWORD,
            receiver_email=RECEIVER_EMAIL,
            cc_emails=[],           # No CC for now
            subject=SUBJECT,
            body=BODY,
            attachment_paths=ATTACHMENTS,
        )
        if status:
            await self.capability_worker.speak("Email has been sent successfully.")
        else:
            await self.capability_worker.speak("Failed to send email")
        # Resume the normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        self.worker.session_tasks.create(self.email_sender())