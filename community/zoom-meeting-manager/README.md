# Zoom Meeting Manager

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@uchebuzz-coder--lightgrey?style=flat-square)

## What It Does

Voice access to your Zoom schedule, meeting details, and cloud recordings. Ask what is next on Zoom, get join links and passcodes, cancel meetings, or (on Pro+) list recordings, summarize transcripts, and play recordings.

## Suggested Trigger Words

- "Zoom meetings"
- "my Zooms"
- "Zoom schedule"
- "today's Zooms"
- "next Zoom"
- "Zoom link"
- "Zoom passcode"
- "cancel Zoom"
- "Zoom recording"
- "summarize Zoom"
- "Zoom transcript"

Configure additional phrases in the OpenHome dashboard for this ability.

## Setup

### Zoom plan requirements

This ability works with **any Zoom plan** for schedule management (view meetings, details, cancel meetings).

**Cloud recording features** (list recordings, summarize transcript, play recording) require **Zoom Pro or higher**. On the free plan, recording-related commands are unavailable; the ability tells you when a feature needs Pro.

### Zoom Server-to-Server OAuth app

1. Go to [marketplace.zoom.us](https://marketplace.zoom.us)
2. Click **Develop** → **Build App**
3. Choose **Server-to-Server OAuth**
4. Name it (for example, "OpenHome")
5. Under **Scopes**, add:
   - `meeting:read:list_meetings:admin` — list and view meetings
   - `meeting:delete:meeting:admin` — delete meetings
   - `cloud_recording:read:list_account_recordings:admin` — list cloud recordings
   - `cloud_recording:read:recording:admin` — view a recording
   - `cloud_recording:read:meeting_transcript:admin` — read meeting transcript
   - `user:read:user:admin` — read user profile (plan detection)
6. Activate the app
7. Copy your **Account ID**, **Client ID**, and **Client Secret**

### Credentials in OpenHome

Add those values in the OpenHome dashboard under this ability's settings. For local development you can set `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, and `ZOOM_CLIENT_SECRET`. Credentials are stored in the ability's persistent storage; access tokens stay in memory and refresh automatically.

## How It Works

After you trigger the ability, it uses the Zoom REST API with Server-to-Server OAuth. It can list today's meetings, find your next meeting (including join details when the start is soon), look up a meeting by time or topic, cancel a meeting with confirmation, and on Pro+ accounts list cloud recordings, fetch transcripts for summaries, and stream or play recordings. Exit words such as "stop" or "exit" end the session.

## Example Conversation

> **User:** "What's my next Zoom?"
> **AI:** "Your next meeting is Team standup at 2:00 PM. It starts in about ten minutes. Here's the join link…"

> **User:** "Cancel my 11 o'clock Zoom"
> **AI:** "I found 'Project sync' at 11:00 AM. Say yes to cancel it or no to keep it."
> **User:** "Yes"
> **AI:** "Done. That meeting has been cancelled."

> **User:** "Any Zoom recordings from this week?"
> **AI:** *(Pro+)* "You have two recordings…"  
> *(Free plan)* "Cloud recordings need a Zoom Pro or higher plan. I can still help with your schedule."
