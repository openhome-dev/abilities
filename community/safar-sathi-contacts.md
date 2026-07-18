# Safar Sathi — Trusted Contacts

Add the names and WhatsApp numbers of the people who should receive emergency alerts.
Phone numbers must be in **E.164 international format** (country code first, with `+`, no spaces or dashes).

Edit the `trusted_contacts` array inside `safar_sathi_state.json` in your ability's user data storage:

```json
"trusted_contacts": [
  {"name": "Saad Hamid Ali",          "phone": "+923055417130"},
  {"name": "Muhammad Ammar",          "phone": "+923494533107"}
]
```

### Important notes

- **Twilio Sandbox testing**: While using the free Twilio WhatsApp Sandbox, every contact must
  first send a one-time opt-in message to your sandbox number
  (e.g. `join <your-sandbox-word>` to `+14155238886`) before they can receive messages.
  This restriction is lifted when you graduate to a Twilio production number.

- **Production**: No opt-in is needed once you have an approved WhatsApp Business number through
  Twilio. The alert fires instantly to any number.

- **Pakistan numbers**: Always include `+92` before the 10-digit number, e.g. `+923001234567`.
