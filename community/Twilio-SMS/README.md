# Twilio SMS & Voice Messenger

A powerful, hands-free communications assistant that lets you send SMS messages, place outbound voice calls with spoken messages (TTS), read incoming texts, manage contacts, and check call/message history using the Twilio REST API. It turns your OpenHome speaker into a complete voice-to-phone communication bridge.

## Trigger Words
**SMS Commands:**
- "send a text"
- "text message"
- "send message"
- "read my texts"
- "check messages"

**Voice Call Commands:**
- "call mom"
- "call dad"
- "phone call"
- "make a call"
- "leave a message"
- "voice message"
- "call history"
- "recent calls"
- "who called me"
- "did my call go through"

## Setup
This Ability requires a Twilio account and an active Twilio phone number. 
*Note: Voice calls work immediately upon setup without any regulatory registration. SMS delivery in the US may require standard A2P 10DLC registration in the Twilio console.*

1. Create an account at [twilio.com](https://www.twilio.com) and purchase a voice/SMS-capable phone number.
2. Run the Ability for the first time. It will automatically generate a `twilio_sms_prefs.json` file in your Ability's directory with default settings (including Voice options like `"voice_say_voice": "alice"`).
3. Open `twilio_sms_prefs.json` and fill in your credentials:
   - `account_sid`: Your Twilio Account SID.
   - `auth_token`: Your Twilio Auth Token.
   - `twilio_number`: Your Twilio phone number (in E.164 format, e.g., `+12345678900`).
4. Save the file. You can now use voice commands to add contacts or manually add them to the `contacts` dictionary.

## How It Works
1. **Trigger:** The user triggers the Ability with a hotword.
2. **Intent Routing:** The Ability uses the LLM to classify the user's intent (e.g., "Send a text to John", "Call Mom and tell her I'll be late", "Read my calls").
3. **Outbound Voice Calls:** It extracts the recipient and message, asks for confirmation, safely XML-escapes the text to prevent TwiML injection, and places an outbound POST request to `/Calls.json`. The recipient's phone rings, and a natural Twilio TTS voice reads the message.
4. **SMS Messaging:** It resolves the contact using fuzzy LLM matching, asks for confirmation, and executes a POST request to `/Messages.json`.
5. **Reading History (Calls & Texts):** It polls the Twilio API for incoming messages or recent call logs. It translates raw API data (like call durations in seconds or timestamps) into natural spoken language (e.g., "The call lasted 2 minutes and 5 seconds").
6. **Safety & Privacy:** Message bodies inserted into TwiML are strictly sanitized using `html.escape()`. Unknown caller numbers are read using only their last 4 digits for privacy.

## Key SDK Functions Used
- `speak()` — Text-to-speech output to talk to the user and read messages/call logs.
- `user_response()` — Listen for user commands and confirmations.
- `text_to_text_response()` — LLM text generation used for intent routing, data extraction, and fuzzy contact resolution (called synchronously without `await`).
- `check_if_file_exists()`, `read_file()`, `write_file()` — Safe, asynchronous persistent state management for preferences and contacts.
- `session_tasks.create()` — Safely runs the main asynchronous interaction loop.
- `editor_logging_handler.error()` — Safe logging of API or internal errors without using `print()`.
- `resume_normal_flow()` — Safely returns control to the Personality, guaranteed to execute via a `finally` block.

## Example Conversation (Voice Call Flow)

**User:** "Make a phone call"  
**AI:** "Twilio is ready. What would you like to do?"  
**User:** "Call John and tell him I am stuck in traffic and will be 10 minutes late."  
**AI:** "I'll call john and say: 'I am stuck in traffic and will be 10 minutes late.'. Place the call?"  
**User:** "Yes"  
**AI:** "Calling john now. The message will play when they pick up. Anything else?"  
**User:** "Did my call go through?"  
**AI:** "Checking call status... Your call went through. It lasted 15 seconds. Anything else?"  
**User:** "Read my recent calls"  
**AI:** "Checking your recent calls... You have 1 recent call. First, You called john today at 5:30 PM, the call lasted 15 seconds. Anything else?"  
**User:** "Stop"  
**AI:** "Goodbye."