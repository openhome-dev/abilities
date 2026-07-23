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

**Summarises any bill or document out loud.** Instead of reading a page of small
print, the user hears what it actually means in three or four sentences: what the
document is, the amount owed, and the one thing on it worth worrying about —
arrears carried over, a late payment penalty, a slab change. Long official
documents get the same treatment: the point first, the detail only if asked.

**Tracks due dates and warns before they pass.** Every document is saved, so
"mera bijli ka bill kab due hai" is answered days later in a brand new
conversation. Rehnuma works out how many days remain from today's date rather
than just repeating the date, and if any saved bill falls due within three days
it opens the conversation with a single reminder line. Late payment surcharges
fall hardest on people who could not read the deadline in the first place.

**Guides the user through filling and completing forms.** For CNIC renewal,
passport applications, bay form / birth registration, and bank and school forms,
Rehnuma explains what each field is asking for and what belongs in it, which
documents to carry, what the fee is, which office to go to, and what to say to
the clerk once there. It walks the user through the process step by step and
answers follow-up questions at any point.

> Rehnuma explains and guides — it does not fill in or submit forms on the
> user's behalf, and it does not make payments. The user, or whoever is helping
> them, stays in control of anything written down or handed over.

**Emails a document on request.** Saying "email kar dein" sends the document to
the address saved on the wallet server — useful when a paper copy has to reach
someone who can read, such as an employer or a relative handling the payment.
The request is routed straight to the server and never to the language model,
which would otherwise be liable to claim it had sent something it had not. If no
address is on file, Rehnuma says so instead of failing silently.

**Answers follow-up questions in context.** "Uska kitna hai", "aur woh gas wala
bill", "agar late ho jaun to kya hoga" all resolve correctly against the saved
documents and the last few turns of conversation.

**Speaks only Roman Urdu** in short sentences, in a male voice, and never tells
the user to read anything.

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
| `POST /api/email_send` | Body `{"hint": "<what the user said>"}`. The server picks the matching document and emails it to the address saved against that user. Returns `{"ok": true}` on success, or `{"error": "no email ..."}` when no address is on file. |

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
