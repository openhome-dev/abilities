# Email Sender Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)

## What This Is
**This is a template ability** that demonstrates how to send emails programmatically through OpenHome using the built-in `send_email()` function in CapabilityWorker. Perfect for building abilities that need to send notifications, reports, or automated emails.

## Why Build This as an Ability

Every OpenHome Agent already has an LLM that can draft emails conversationally. **But the LLM can't actually send emails on its own.** This template shows you how to:

- **Actually send emails** — not just draft them in conversation
- **Automate email workflows** — send reports, alerts, confirmations
- **Integrate with external systems** — trigger emails based on API data or user actions
- **Attach files** — send documents, images, or generated reports

**Key insight:** If all you need is help writing an email, use the Agent's LLM. If you need to *actually send* an email automatically, build an ability.

## What You Can Build

Examples of abilities you could create with this template:
- **Daily digest emailer** — Send morning briefings or summaries
- **Alert system** — Email notifications when conditions are met
- **Report generator** — Create and email weekly reports
- **Reminder system** — Send scheduled reminders via email
- **File sharer** — Email documents or attachments on command
- **Multi-recipient broadcasts** — Send emails to groups with CC
- **Form submission handler** — Email form responses to recipients

## Setup Requirements

### 1. Gmail App Password (Recommended)
For Gmail accounts, you'll need an app-specific password:

1. **Enable 2-Factor Authentication** on your Gmail account
2. Go to [Google Account → Security → App passwords](https://myaccount.google.com/apppasswords)
3. Generate a new app password for "Mail"
4. Copy the 16-character password (spaces don't matter)
5. Use this password in `SENDER_PASSWORD` (not your regular Gmail password)

**Why?** Gmail doesn't allow regular passwords for SMTP access from apps. App passwords are safer and can be revoked independently.

### 2. SMTP Server Details
The template is configured for Gmail by default:
- **Host:** `smtp.gmail.com`
- **Port:** `465` (SSL)

**For other email providers:**
| Provider | SMTP Host | Port | Security |
|----------|-----------|------|----------|
| **Gmail** | smtp.gmail.com | 465 | SSL |
| **Outlook** | smtp-mail.outlook.com | 587 | TLS |
| **Yahoo** | smtp.mail.yahoo.com | 465 | SSL |
| **Office 365** | smtp.office365.com | 587 | TLS |
| **Custom** | Your SMTP server | Varies | Check provider |

### 3. File Attachments (Optional)
Place attachment files in your ability's directory. The template looks for `testfile.txt` — replace with your own files.

## Template Configuration

Update these hardcoded values in `email_sender()`:

```python
# ── Hardcoded config ──────────────────────────────────────
HOST            = "smtp.gmail.com"              # Your SMTP server
PORT            = 465                            # 465 for SSL, 587 for TLS
SENDER_EMAIL    = "your_email@gmail.com"        # Your email address
SENDER_PASSWORD = "xxxx xxxx xxxx xxxx"         # Your app password
RECEIVER_EMAIL  = "recipient@example.com"       # Recipient's email
SUBJECT         = "Test Email"                   # Email subject line
BODY            = "Hello! This is a test."       # Email body text
ATTACHMENTS     = ["testfile.txt"]               # Files to attach (optional)
# ─────────────────────────────────────────────────────────
```

## The send_email() Function

The template uses `CapabilityWorker.send_email()` — OpenHome's built-in email function.

**Function Signature:**
```python
def send_email(
    self,
    host: str,
    port: int,
    sender_email: str,
    sender_password: str,
    receiver_email: str,
    cc_emails: list,
    subject: str,
    body: str,
    attachment_paths: list = []
) -> bool
```

**Parameters:**
- `host` (str): SMTP server address (e.g., "smtp.gmail.com")
- `port` (int): SMTP port (465 for SSL, 587 for TLS)
- `sender_email` (str): Your email address
- `sender_password` (str): Your email password or app password
- `receiver_email` (str): Recipient's email address
- `cc_emails` (list): List of CC email addresses (empty list `[]` for none)
- `subject` (str): Email subject line
- `body` (str): Email body text (plain text)
- `attachment_paths` (list): List of filenames to attach (files must be in ability directory)

**Returns:** `bool` — `True` if email sent successfully, `False` if failed

**Template Usage:**
```python
status = self.capability_worker.send_email(
    host="smtp.gmail.com",
    port=465,
    sender_email="sender@gmail.com",
    sender_password="app_password_here",
    receiver_email="recipient@example.com",
    cc_emails=[],
    subject="Subject Line",
    body="Email body text",
    attachment_paths=["file.txt"]
)

if status:
    await self.capability_worker.speak("Email sent successfully!")
else:
    await self.capability_worker.speak("Failed to send email.")
```

## How the Template Works

### Template Flow
1. User triggers the ability with configured trigger words
2. Ability loads hardcoded email configuration
3. Calls `send_email()` with all parameters
4. Checks return status (`True` = success, `False` = failure)
5. Speaks confirmation or error message
6. Calls `resume_normal_flow()` to return control to Agent

### Template Code Walkthrough

**1. Initialize Workers:**
```python
def call(self, worker: AgentWorker):
    self.worker = worker
    self.capability_worker = CapabilityWorker(self.worker)
    self.worker.session_tasks.create(self.email_sender())
```
- Sets up ability infrastructure
- Creates async task using `session_tasks` (not raw asyncio)

**2. Configure Email:**
```python
async def email_sender(self):
    HOST = "smtp.gmail.com"
    PORT = 465
    SENDER_EMAIL = "test@gmail.com"
    SENDER_PASSWORD = "test 1234 5678 9121"
    RECEIVER_EMAIL = "receiver_test@gmail.com"
    SUBJECT = "Test Email"
    BODY = "Hello! This is a test email."
    ATTACHMENTS = ["testfile.txt"]
```
- Hardcoded for simplicity in template
- In production, load from file storage or user input

**3. Send Email:**
```python
status = self.capability_worker.send_email(
    host=HOST,
    port=PORT,
    sender_email=SENDER_EMAIL,
    sender_password=SENDER_PASSWORD,
    receiver_email=RECEIVER_EMAIL,
    cc_emails=[],
    subject=SUBJECT,
    body=BODY,
    attachment_paths=ATTACHMENTS,
)
```
- Calls built-in send_email function
- Returns boolean status

**4. Confirm & Resume:**
```python
if status:
    await self.capability_worker.speak("Email has been sent successfully.")
else:
    await self.capability_worker.speak("Failed to send email")

self.capability_worker.resume_normal_flow()  # ← CRITICAL: Always call this
```

## Advanced Patterns

### Pattern 1: Email with Generated Attachment
```python
async def email_with_generated_report(self):
    # Generate report content
    report_content = generate_report()  # Your logic
    
    # Write to file in ability directory
    with open("report.txt", "w") as f:
        f.write(report_content)
    
    # Send email with attachment
    status = self.capability_worker.send_email(
        host="smtp.gmail.com",
        port=465,
        sender_email="reports@company.com",
        sender_password="your_app_password",
        receiver_email="manager@company.com",
        cc_emails=[],
        subject="Weekly Report",
        body="Please find the attached weekly report.",
        attachment_paths=["report.txt"]
    )
    
    if status:
        await self.capability_worker.speak("Report emailed successfully.")
    else:
        await self.capability_worker.speak("Failed to email report.")
    
    self.capability_worker.resume_normal_flow()
```

### Pattern 2: Load Email Config from File Storage
```python
async def send_configured_email(self):
    # Load email configuration from persistent storage
    if await self.capability_worker.check_if_file_exists("email_settings.json", in_ability_directory=False):
        raw = await self.capability_worker.read_file("email_settings.json", in_ability_directory=False)
        config = json.loads(raw)
    else:
        await self.capability_worker.speak("Email not configured. Please set up your email first.")
        self.capability_worker.resume_normal_flow()
        return
    
    # Send using stored config
    status = self.capability_worker.send_email(
        host=config["host"],
        port=config["port"],
        sender_email=config["sender_email"],
        sender_password=config["sender_password"],
        receiver_email=config["default_recipient"],
        cc_emails=config.get("cc_emails", []),
        subject="Automated Email",
        body="This email was sent from your OpenHome ability.",
        attachment_paths=[]
    )
    
    if status:
        await self.capability_worker.speak("Email sent using saved configuration.")
    else:
        await self.capability_worker.speak("Failed to send email.")
    
    self.capability_worker.resume_normal_flow()
```

### Pattern 3: Email with LLM-Generated Content
```python
async def send_ai_composed_email(self):
    # Ask user for email purpose
    await self.capability_worker.speak("What should the email be about?")
    topic = await self.capability_worker.user_response()
    
    # Generate email body using LLM
    email_prompt = f"""Write a professional email about: {topic}
    Keep it concise (2-3 paragraphs).
    Use a friendly but professional tone."""
    
    email_body = self.capability_worker.text_to_text_response(email_prompt)
    
    # Send the AI-generated email
    status = self.capability_worker.send_email(
        host="smtp.gmail.com",
        port=465,
        sender_email="your_email@gmail.com",
        sender_password="your_app_password",
        receiver_email="recipient@example.com",
        cc_emails=[],
        subject=f"Re: {topic}",
        body=email_body,
        attachment_paths=[]
    )
    
    if status:
        await self.capability_worker.speak("AI-composed email sent successfully.")
    else:
        await self.capability_worker.speak("Failed to send email.")
    
    self.capability_worker.resume_normal_flow()
```

## Best Practices

### 1. Never Hardcode Passwords in Production
```python
# ❌ BAD — Password visible in code
SENDER_PASSWORD = "mypassword123"

# ✅ GOOD — Load from secure file storage
if await self.capability_worker.check_if_file_exists("email_creds.json", in_ability_directory=False):
    raw = await self.capability_worker.read_file("email_creds.json", in_ability_directory=False)
    creds = json.loads(raw)
    SENDER_PASSWORD = creds["app_password"]
```

### 2. Validate Email Addresses
```python
import re

def is_valid_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# Use before sending
if not is_valid_email(recipient_email):
    await self.capability_worker.speak("Invalid email address. Please try again.")
    return
```

### 3. Handle Errors Gracefully
```python
try:
    status = self.capability_worker.send_email(...)
    if status:
        await self.capability_worker.speak("Email sent successfully.")
    else:
        await self.capability_worker.speak(
            "Failed to send email. Check your SMTP settings and credentials."
        )
except Exception as e:
    self.worker.editor_logging_handler.error(f"Email error: {e}")
    await self.capability_worker.speak("An error occurred while sending the email.")
finally:
    self.capability_worker.resume_normal_flow()
```

### 4. Add Confirmation for Important Emails
```python
# Read back email details before sending
await self.capability_worker.speak(
    f"I'll send an email to {recipient_email} with subject '{subject}'. "
    "Should I proceed?"
)

confirmed = await self.capability_worker.run_confirmation_loop("Confirm sending?")

if confirmed:
    status = self.capability_worker.send_email(...)
else:
    await self.capability_worker.speak("Email cancelled.")
```

### 5. Use Descriptive Subject Lines
```python
from datetime import datetime

# ✅ GOOD — Descriptive with context
subject = f"Daily Report - {datetime.now().strftime('%B %d, %Y')}"
subject = f"Alert: System Status Changed"
subject = f"Re: {user_topic}"

# ❌ BAD — Generic
subject = "Email"
subject = "Test"
```

## Troubleshooting

### "Failed to send email"
**Possible causes:**
1. Wrong SMTP host or port
2. Invalid credentials (use app password for Gmail, not regular password)
3. 2FA not enabled (required for Gmail app passwords)
4. Firewall blocking SMTP port
5. Incorrect sender email address

**Solutions:**
- Verify SMTP settings for your provider
- Regenerate app password
- Check `editor_logging_handler` for detailed error messages

### Attachment Not Found
**Problem:** Email sends but attachment is missing

**Solution:** Files must be in your ability's directory:
```python
# Place files in: /your-ability-folder/testfile.txt
ATTACHMENTS = ["testfile.txt"]  # Just filename, not full path
```

### Gmail "Less Secure Apps" Error
**Problem:** Gmail blocks login

**Solution:** Don't use "Allow less secure apps" (deprecated). Use app passwords instead:
1. Enable 2-Factor Authentication
2. Generate app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Use 16-character app password (not your regular password)

### Email Sends But Gets Marked as Spam
**Solutions:**
- Add a professional email signature
- Use descriptive subject lines (avoid "Test", "Hi", etc.)
- Don't send too many emails rapidly
- Consider using a custom domain (not Gmail) for bulk sending

## Security Considerations

### 🔒 Important Security Notes
- **Never commit passwords to GitHub** — Use file storage or environment variables
- **Use app passwords** — Never use your main account password
- **Limit recipient access** — Don't allow users to specify arbitrary recipients without validation
- **Rate limit sending** — Prevent spam/abuse by limiting emails per session
- **Validate all inputs** — Check email addresses, file paths, subject lines

### Recommended: Encrypt Stored Credentials
```python
# Don't store plain text passwords in files
# Use encryption or OpenHome's secure storage (if available)
# At minimum, use file permissions to restrict access
```

## Quick Start Checklist

### Setup (One-Time)
- [ ] Get SMTP credentials from your email provider
- [ ] For Gmail: Enable 2FA and generate app password
- [ ] Update `HOST`, `PORT`, `SENDER_EMAIL`, `SENDER_PASSWORD` in template
- [ ] (Optional) Add attachment files to ability directory
- [ ] Test with a simple email to yourself

### Building Your Ability
- [ ] Customize trigger words in the OpenHome dashboard
- [ ] Replace hardcoded values with dynamic inputs or file storage
- [ ] Add email address validation
- [ ] Implement error handling with try-catch
- [ ] Add confirmation prompts for important sends
- [ ] Test with various recipients and attachments
- [ ] Consider loading config from persistent storage

## Links & Resources

**Email Provider SMTP Docs:**
- [Gmail SMTP Settings](https://support.google.com/mail/answer/7126229)
- [Outlook SMTP Settings](https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-8361e398-8af4-4e97-b147-6c6c4ac95353)
- [Yahoo SMTP Settings](https://help.yahoo.com/kb/SLN4724.html)

**OpenHome:**
- [Dashboard](https://app.openhome.xyz/dashboard)
- [Official Documentation](https://docs.openhome.com)
- [Discord Community](https://discord.com/channels/1197724389630824508)

## Final Reminder

⚠️ **This template demonstrates email sending, not a complete ability.**

Use it to learn how to:
- ✅ Send emails programmatically
- ✅ Attach files to emails
- ✅ Handle CC recipients
- ✅ Check send status and handle errors

Then build something useful with this foundation! 🚀

---

**Remember:** Email is powerful — use it responsibly. Don't spam, always validate recipients, and respect rate limits.
