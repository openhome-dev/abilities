This is a basic capability template.
# Twilio SMS Messenger

A powerful, hands-free texting assistant that lets you send SMS messages, read incoming texts, manage your contacts, and check delivery statuses using the Twilio REST API. It turns your OpenHome speaker into a two-way voice-to-SMS bridge.

## Trigger Words
- "send a text"
- "text message"
- "send message"
- "read my texts"
- "check messages"

## Setup
This Ability requires a Twilio account and an active Twilio phone number.
1. Create an account at [twilio.com](https://www.twilio.com) and purchase an SMS-capable phone number.
2. Run the Ability for the first time. It will automatically generate a `twilio_sms_prefs.json` file in your Ability's directory.
3. Open `twilio_sms_prefs.json` and fill in your credentials:
   - `account_sid`: Your Twilio Account SID.
   - `auth_token`: Your Twilio Auth Token.
   - `twilio_number`: Your Twilio phone number (in E.164 format, e.g., `+12345678900`).
4. Save the file. You can now use voice commands to add contacts or manually add them to the `contacts` dictionary in the JSON file.

## How It Works
1. User triggers the Ability with a hotword.
2. The Ability welcomes the user and asks what they would like to do.
3. User states their intent (e.g., "Send a text to John", "Read my messages", "Add a contact").
4. The Ability uses the LLM to classify the intent and extract necessary data (contact names, message body, phone numbers).
5. For sending: It resolves the contact using exact or fuzzy LLM matching, asks for confirmation, and executes a POST request to the Twilio API.
6. For reading: It polls the Twilio API for incoming messages, expands common SMS abbreviations for Text-to-Speech (TTS), limits reading to the latest unread messages, and safely reads out the contents.
7. User can continue giving commands or say "stop" to exit.

## Key SDK Functions Used
- `speak()` — Text-to-speech output to talk to the user and read messages.
- `user_response()` — Listen for user commands and confirmations.
- `text_to_text_response()` — LLM text generation used for intent routing, data extraction, and fuzzy contact resolution (called synchronously without `await`).
- `session_tasks.create()` — Safely runs the main asynchronous interaction loop.
- `editor_logging_handler.error()` — Safe logging of API or internal errors without using `print()`.
- `resume_normal_flow()` — Safely returns control to the Personality, guaranteed to execute via a `finally` block.

## Example Conversation

**User:** "Send a text"  
**AI:** "Twilio SMS is ready. What would you like to do?"  
**User:** "Send a text to John saying I will be there in 5 minutes"  
**AI:** "I'll text john: 'I will be there in 5 minutes'. Should I send it?"  
**User:** "Yes"  
**AI:** "Sending... Message sent to john. Anything else?"  
**User:** "Did my text go through?"  
**AI:** "Checking delivery status... Your message was delivered. Anything else?"  
**User:** "Read my texts"  
**AI:** "Checking your messages... You have 1 new message. First, from john today at 5:30 PM: Okay, see you soon. Anything else?"  
**User:** "Stop"  
**AI:** "Goodbye."