# Check-In Companion

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

## What It Does
A daily check-in for someone who lives alone, such as an older parent, and a short evening email for their family.

At the times they choose, the speaker asks one warm question ("Morning, Jean. How did the dentist go?"). It understands the answer, not just that someone spoke. If there's no answer, it asks once more, then emails family. If they mention a fall, chest pain or trouble breathing, it tells them to call for help and emails family straight away. Every evening family get a few lines: whether each check-in was answered, a mood word, anything worth knowing, and only the news the person was happy to share. **Never a transcript.**

Amazon retired its Alexa Together check-in service. What's left elsewhere only tells family that the device was used. Check-In Companion has a short conversation, keeps the person in control of what's shared, needs no camera and has no subscription.

> **Not an emergency service.** It can miss things, and it only works while the device is on and connected. For emergencies, call your local emergency number. The [Panic Protocol](../panic-protocol/) ability can call emergency contacts.

## How It's Different From Similar Abilities
- **medication-reminder** reminds about pills. This asks how the person is and tells family.
- **panic-protocol** calls contacts when the user asks for help. This notices when they *don't* answer, or mention a worry without asking.
- **KindMind** and **celebration-engine** talk only to the user. This one closes the loop with family, with the user's consent.

## Suggested Trigger Words
- "check in"
- "check-in"
- "I'm here"
- "check-in settings"
- "what have you told my family"

Scheduled check-ins need no trigger. The background part asks at the set times whenever the session is connected.

## Setup
Whoever installs it (often an adult child) does this once in OpenHome Settings:

1. **Family emails:** add an API key named `checkin_family_emails` with up to 5 addresses, separated by commas.
2. **Sending:** link a Google account. Emails are sent from it through Gmail.
   **Or**, without a linked account, add `checkin_sender_email` and `checkin_sender_password` (a Gmail app password) to send by SMTP.
3. Optionally, say "my emergency number is 999" (or your local number) so the safety prompt names it.

The defaults are a check-in at 9:30 am and the family email at 7 pm, in the device's timezone. Change both by voice.

## How It Works
**Background (`background.py`)** checks once a minute.

| When | What happens |
|---|---|
| A check-in time arrives | It asks one short question out loud. The question uses the person's name and at most one personal touch: something from yesterday's chat, a reminder from earlier today ("How did the dentist go?"), or a family member they may have heard from. If a medication dose isn't marked as taken yet, it adds a gentle aside. |
| They answer | It reads the answer from the conversation and notes a mood (1 to 5), any worries (fall, pain, dizziness, chest pain, breathing, confusion, not eating, low mood, loneliness, poor sleep) and a short note they'd be happy for family to hear. |
| No answer within 20 minutes | It asks once more, gently. |
| Still no answer 20 minutes later | It marks the check-in missed and emails family: "Jean didn't answer the 9:30 am check-in... You might want to give them a call." It says only when they last spoke to the speaker, never what they said. |
| A fall, chest pain, trouble breathing or a plea for help is mentioned | It says "That sounds serious. If you need help right now, please call ..." and sends an urgent email. This happens at most once every two hours, and never twice for the same words. |
| The digest time arrives | It sends one email: each check-in answered, missed or not asked, the day's mood, anything worth knowing, the shared notes, a weekly mood trend, and when they were last heard from. |

Between check-ins it also listens for the same worries in everyday conversation. Only phrases that look like a health worry reach the LLM, at most two a minute. It stores the *type* of worry, never the words. The person can turn this off by voice.

While a check-in question is open, it writes `checkin_context.md`, a short hint that tells the main Agent to reply warmly and briefly and not give medical advice. The hint is removed when the check-in is answered or missed.

**Voice skill (`main.py`)**

| You say | It does |
|---|---|
| "Check in" | Asks three short questions: how you are, food and plans, anything for family. It records them like a scheduled check-in, so a scheduled one within the next two hours is skipped. If a dose isn't marked as taken yet, it mentions that at the end. |
| "Check in at 9 and 7" / "stop the evening one" | Confirms, then changes the times (up to 3 a day). You can answer the confirmation with a change ("no, make it 10"). |
| "Send the family email at 8" | Changes the digest time after you confirm. |
| "I'm at my daughter's until Sunday" | Pauses check-ins, alerts and digests after you confirm, and emails family that check-ins are paused. They restart by themselves after the pause. |
| "Start check-ins again" | Ends a pause early. |
| "Keep today private" | Family hear only that you checked in and how you seemed, never what you said. |
| "What have you told my family?" | Reads back a short summary of the last evening email. |
| "Stop listening between check-ins" / "start again" | Turns the everyday worry listening off or on. |
| "My emergency number is 999" | Saves the number used in the safety prompt. |
| "When's my next check-in?" | Gives the times, any pause, and how many people get the email. |
| "What can you do?" | Names two things, then offers more, so you never hear a long list. |

Pausing and setting the emergency number both accept a change in reply ("no, until Monday", "no, it's 112").

Say "that's all", "stop" or "goodbye" at any prompt to leave. "I'm good" and "nothing" count as answers, not exits. Two silent turns also end the session.

## What Family See, and What They Never See
- **They see:** answered or missed for each check-in, a mood word, worry types ("mentioned feeling dizzy"), short notes the person was happy to share, a weekly mood trend, and roughly when they last spoke to the speaker.
- **They never see:** transcripts, recordings, medication details, or anything the person asked to keep private.

## Reuses What Other Abilities Already Know
It never asks for anything OpenHome already has. Each source is read-only and optional, and it's skipped quietly if that ability isn't installed.

| Source | Used for |
|---|---|
| `user_profile.md`, `user_summary.md` (OpenHome memory) | The person's first name. |
| `memory_mirror_corrections.md` ([Memory Mirror](../memory-mirror/)) | A name the person corrected there. |
| `upcoming_schedule.md` ([Timers, Alarms & Reminders](../timers-alarms-reminders/)) | Asking about something from earlier today. Alarms are ignored. |
| `social_memory.json` ([Social Memory](../social-memory/)) | Names of family members, for a natural question. Only names and relationships are read, never the conversation snippets. |
| `medication_reminder_data` ([Medication Reminder](../medication-reminder/)) | A gentle spoken aside when a dose is 30 minutes or more overdue and not marked as taken or skipped. **This is only ever spoken to the person, never sent to family.** |

## Data
- Settings, today's record and a 21-day log are kept in Context Storage under `checkin_state`. The log holds dates, statuses, mood numbers, worry types and the shared notes.
- `checkin_busy` keeps the background out while the voice skill is open.
- Other abilities' data (see above) is read only. It is never written, logged or emailed.
- Logs record event types only, never words, names or email addresses.

## Limits
- **Only while the session is connected.** If the device is off or offline at check-in time, the check-in is "not asked", not "missed", and no alert is sent. The digest says so. **If family get no evening email at all, that itself is a reason to call.**
- **Within two hours.** A check-in time is only asked within two hours of the time. A device that comes online later skips it.
- **Answers are read from the conversation.** Anything said after the question counts as an answer, even a request to the assistant. That still shows the person is there.
- **Speech recognition can mishear,** so a worry can be missed or misread. Treat alerts as a prompt to call, not a diagnosis.
