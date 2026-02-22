# Flight Information Email Capability

An OpenHome capability that enables natural-language flight searches via the **Amadeus Flight Offers API** and sends results directly to email using **Composio + Gmail**.

## Features

- Natural language input (e.g. "flight information from Dhaka to Singapore on March 2")
- Supports Bengali/Devanagari city names (ढाका → DAC, सिंगापुर → SIN, बैंकोक → BKK)
- Saves the last search result — can send even if no flights are found
- Clean, formatted email with top options + live booking links (Google Flights & Kayak)
- Very reliable send triggers:  
  "yes send", "please send", "send email", "send those details in my email", short "yes", etc.

## Requirements

- Python 3.8+
- OpenHome platform (custom capability)
- Composio account (Gmail integration)
- Amadeus Self-Service API test key (free tier)

## Setup Instructions

### 1. Get Amadeus API Credentials (Test Environment)

1. Go to [https://developers.amadeus.com/](https://developers.amadeus.com/)
2. Sign up / log in
3. Create a new app → select **Test** environment
4. After creation, copy:
   - **Client ID** (API Key)
   - **Client Secret**
5. Paste them into the code:

```python
AMADEUS_API_KEY    = "your_client_id_here"
AMADEUS_API_SECRET = "your_client_secret_here"
```
### 2. Get Composio Gmail Credentials

1. Go to [https://composio.dev/](https://composio.dev/)
2. Sign up / log in
3. Go to **Integrations** → search for **Gmail** → click **Connect**
4. Authenticate with your Gmail account (e.g. Fiction1729@gmail.com)
5. After connection, go to **Connected Accounts** → copy:
   - **Connected Account ID** (e.g. `ca_xxxxxxxxxxxx`)
   - **User ID** (e.g. `pg-test-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
6. Your **API Key** is shown in the dashboard (top right or API Keys section)
7. Paste them into the code:

```python
COMPOSIO_API_KEY              = "ak_xxxxxxxxxxxxxxxxxxxxxxxx"
COMPOSIO_USER_ID              = "pg-test-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
COMPOSIO_CONNECTED_ACCOUNT_ID = "ca_wstbA82EwN74"  # ← replace with your actual ID
```
### 3. Install Dependencies (if testing locally)
```bash
pip install requests
```

(OpenHome already includes most dependencies.)
### 4. Add the capability to OpenHome

**Create folder**: add-flight-information-email
(inside your capabilities directory, e.g. src/agent/capabilities/)
Inside that folder create two files:
main.py
README.md

Paste the full code into main.py
Paste this README content into README.md
Restart OpenHome or reload capabilities

How to Use
Just speak naturally:

"flight information from Dhaka to Bangkok"
"flight information from ढाका to सिंगापुर on March 2"
"Flight information. February 25. Singapur."

After results appear, say any of these to send:

"yes send"
"yes, send"
"please send"
"send email"
"send those details in my email"
"yes send email"
"mail me"

**Agent response:**
"Email sent to your_email@gmail.com! Check your inbox shortly. Safe travels!"
Check Spam / Promotions folder — Composio emails sometimes land there.
Troubleshooting

**"Email sent"** but no email arrives
→ Check Composio dashboard → Recent Actions / Logs
→ Look for rate limits, delivery errors, or invalid recipient
"I can't send emails directly..."
→ Use stronger phrase: "Send email now" or "Yes send email"
No flights found
→ Try different dates or cities

## Future Improvements (optional)

Add real-time Composio response logging
Support return flights
Add filters: preferred airline, nonstop only

Enjoy your flight assistant! ✈️
Reyad – February 2026