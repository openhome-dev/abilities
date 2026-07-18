# Rehnuma — Urdu Bill & Document Reader

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@muj25-lightgrey?style=flat-square)

A spoken Urdu guide for people who cannot read. Rehnuma explains utility bills and
official documents out loud, walks the user through government processes like CNIC
renewal and passport applications, and remembers saved bills so questions asked days
later still get an answer.

Roughly 40% of adults in Pakistan cannot read their own electricity bill. Rehnuma is
the neighbourhood scribe that used to sit in every mohalla, rebuilt as a voice ability.

## What It Does

- Explains a bill out loud: the amount, the due date, one warning worth knowing
  (arrears, late payment penalty), and where to pay
- Answers follow-up questions about saved bills — "mera bijli ka bill kab due hai"
  works in a brand new conversation, days later
- Warns once at the start of a conversation if a saved bill is due within 3 days
- Guides government processes: CNIC renewal, passport, bay form / birth
  registration, plus bank and school forms — documents to bring, fee, which office,
  what to say to the clerk
- Speaks only Roman Urdu in short sentences, and never tells the user to read
  anything

## Suggested Trigger Words

Set these in the OpenHome dashboard. Because Hindi speech-to-text returns
Devanagari, add the Devanagari spellings too:

- "rehnuma"
- "rahnuma"
- "रहनुमा"
- "रहनुमा बुलाओ"

Keep the trigger words to name variants only. Broad triggers like "bill" will
hijack messages meant for the Personality.

## Setup

**No setup required** for government process guidance — that works out of the box.

**Optional — the document wallet.** To let Rehnuma read bill photos and remember
them, run your own wallet server (a phone upload page plus a vision model to extract
the bill) and save its base URL in OpenHome under
**Settings → API Keys** with the name:

```
rehnuma_server_url
```

Use your own server's URL, for example `YOUR_SERVER_URL_HERE`. The ability never
stores the URL in code. If the key is absent, Rehnuma logs it once and keeps working
without documents.

Your wallet server must expose two read-only JSON endpoints:

| Endpoint | Returns |
|---|---|
| `GET /api/documents` | A JSON array of every saved document. Each entry holds the extracted fields (issuer, amount, due date, notes) plus a short description label used to match spoken references like "woh gas wala bill". |
| `GET /api/pending` | `{"data": ...}` when an upload has arrived that has not been spoken about yet, otherwise an empty object. |

Both are called with an 8 second timeout, and any failure degrades quietly to
"no documents" rather than breaking the conversation.

### Recommended Personality Settings

- Language: Hindi (there is no Urdu TTS voice; a Hindi male voice speaking Roman
  Urdu is the closest match)
- Pick a Hindi male voice — Rehnuma refers to itself in the masculine

## How It Works

1. User triggers the ability by name
2. Rehnuma checks the wallet for an upload nobody has explained yet — if one is
   waiting, it explains it immediately, before the user has to ask
3. Every question is answered against the full saved document set, today's date,
   and the last few conversation turns, so "uska kitna hai" resolves correctly
4. New uploads landing mid-conversation are picked up on the next turn
5. Saying "shukriya", "bas", "khatam", "stop" or their Devanagari equivalents exits
   and returns control to the Personality

## Example Conversation

> **User:** "rehnuma"
> **AI:** "Ji, aap ka bheja hua kaghaz mil gaya hai. Suniye. Yeh bijli ka bill hai, 2400 rupay ka. Aakhri tareekh 15 July hai. Is mein 300 rupay purana baqaya bhi shamil hai."
> **User:** "agar late ho jaun to kya hoga"
> **AI:** "Tareekh ke baad raqam barh kar 2650 rupay ho jaye gi. Zyada der hui to connection kat sakta hai, is liye 15 July se pehle jama kara dijiye."
> **User:** "mera shanakhti card expire ho gaya hai kya karun"
> **AI:** "Aap NADRA ke daftar ja kar renew kara sakte hain, ya Pak-ID app se ghar baithe. Purana card aur ek form darkar hoga, fees 750 rupay hai. Urgent chahiye to 2050 rupay lagte hain."
> **User:** "shukriya"
> **AI:** "Theek hai, Allah Hafiz. Zaroorat ho to phir bula lijiye ga."

## Key SDK Functions Used

- `speak()` — spoken output
- `user_response()` — listen for the next turn
- `text_to_text_response()` — answering with a system prompt carrying documents and date
- `get_api_keys()` — runtime lookup of the wallet server URL
- `session_tasks.create()` — launching the conversation loop
- `resume_normal_flow()` — returning control to the Personality on every exit path

## Author

Built by [@muj25](https://github.com/muj25) for the Algoryc
1-Day Hackathon, Islamabad. Licensed MIT.
