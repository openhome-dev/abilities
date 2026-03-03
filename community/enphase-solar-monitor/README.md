# Enphase Solar Monitor

Voice-activated solar dashboard for Enphase systems (IQ Gateway with microinverters).

## Demo Mode

**This ability is built and tested in DEMO MODE** since we don't have a real Enphase system. With `DEMO_MODE = True` (default in `main.py`):

- No credentials or prefs file required
- Returns realistic fake data: 4.2 kW production, 73% battery charging, 3.1 kW consumption
- Lets you test the full voice flow in OpenHome without Enphase hardware

**To use a real system:** Set `DEMO_MODE = False` in `main.py` and follow the setup instructions below.

## What It Does

Ask "how's my solar?" to get real-time production, consumption, and battery status. Data is delivered as natural spoken responses.

## Trigger Words

- "solar"
- "how's my solar"
- "solar status"
- "solar production"
- "battery level"
- "battery status"
- "am I exporting"
- "grid status"
- "solar today"
- "enphase"
- "solar panels"

---

## How to Get Real Enphase API Data

Follow these steps to connect the ability to your actual Enphase solar system.

### Prerequisites

- Enphase solar system with IQ Gateway (microinverters)
- Enphase account with your system linked (see [MyEnphase](https://my.enphase.com))
- If your account shows "not associated with any systems," contact your installer or use [Ownership Transfer](https://enphase.com/ownership-transfer) if you bought a property with an existing system

---

### Step 1: Create an Enphase Developer Account

1. Go to [developer-v4.enphase.com/signup](https://developer-v4.enphase.com/signup)
2. Fill in your details and sign up
3. Check your email and activate your account
4. Log in to the [Enphase Developer Portal](https://developer-v4.enphase.com)

---

### Step 2: Create an Application

1. Go to [Applications](https://developer-v4.enphase.com/admin/applications)
2. Click **Create Application**
3. Fill in:
   - **Name:** e.g. "OpenHome Solar Monitor"
   - **Description:** e.g. "Voice-activated solar monitoring for OpenHome"
   - **Plan:** Select **Watt** (free, 1,000 requests/month)
   - **Access Control:** Check **System Details**, **Site Level Production Monitoring**, **Site Level Consumption Monitoring**
4. Click **Create Application**
5. Copy and save these values from your application page:
   - **API Key**
   - **Client ID**
   - **Client Secret**
   - **Authorization URL** (or note the Client ID to build it)

---

### Step 3: Get Your System ID

Your system must be linked to your Enphase account.

**Option A: Enlighten Web**
1. Go to [enlighten.enphaseenergy.com](https://enlighten.enphaseenergy.com)
2. Log in and open your system
3. Check the browser URL: `https://enlighten.enphaseenergy.com/systems/1234567/...`
4. The number after `/systems/` is your **system_id** (e.g. `1234567`)

**Option B: Enphase Mobile App**
1. Open the Enphase Enlighten app
2. Go to **Settings** or **System**
3. Find **System ID** or **System details**

---

### Step 4: OAuth 2.0 Authorization (Get access_token and refresh_token)

You must authorize your app to access your system data. The system owner (you) must complete this flow.

#### 4a. Build the Authorization URL

Use this format (replace `YOUR_CLIENT_ID` with your Client ID):

```
https://api.enphaseenergy.com/oauth/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=https://api.enphaseenergy.com/oauth/redirect_uri
```

#### 4b. Open the URL in Your Browser

1. Paste the authorization URL into your browser
2. Log in with your Enphase (Enlighten) credentials
3. Approve access when prompted
4. You will be redirected to a page with a **code** in the URL
5. Copy the `code` value (everything after `code=`)

#### 4c. Exchange the Code for Tokens

Send a POST request to Enphase to exchange the authorization code for `access_token` and `refresh_token`. See the Enphase API docs for the exact request format.

---

### Step 5: Configure the Preferences File

1. Copy `enphase_solar_prefs.json.example` to `enphase_solar_prefs.json` in this ability folder
2. Fill in all values (system_id, api_key, client_id, client_secret, access_token, refresh_token, has_battery, has_consumption)
3. With OpenHome File Storage API, prefs are stored in user-level storage

---

### Step 6: Switch to Real Mode

1. Open `main.py`
2. Set `DEMO_MODE = False` at the top
3. Upload the ability to OpenHome

---

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Your account is not associated with any systems" | Contact your installer to link your system, or use Ownership Transfer |
| "Token refresh failed: 401" | Re-run the OAuth flow (Step 4) to get new tokens |
| "I can't find that system ID" | Verify system_id in Enlighten URL or app |
| "I've hit the API limit" | Free tier = 1,000 requests/month; wait or upgrade plan |

### Ability Not Activating?

1. **Add ability to your Personality** – In OpenHome, ensure this ability is added/enabled
2. **Check trigger words** – Verify trigger words in the Abilities Dashboard
3. **Re-upload** – Re-upload the ability zip and ensure it's enabled
4. **Try exact phrases** – Say "How's my solar?" or "Solar status" clearly

---

## OpenHome Compatibility

This ability is built for the OpenHome sandbox:

- **No `open()` or `os`** – Uses OpenHome File Storage API (`check_if_file_exists`, `read_file`, `write_file`) for preferences
- **Hardcoded config** – `unique_name` and `matching_hotwords` are hardcoded from `config.json` (file access forbidden at registration time)
- **Persistent storage** – Preferences are stored with `temp=False` (user-level storage)

---

## Technical Details

- **API:** Enphase Cloud API v4
- **Auth:** OAuth 2.0 with auto-refresh on 401
- **Rate Limit:** 1,000 requests/month (free Watt plan)
- **Caching:** 15-minute TTL

---

## Example

> **User:** "How's my solar?"
>
> **Response:** "You're producing 4.2 kilowatts right now, as of about 15 minutes ago. Today you've generated 28 kilowatt hours. Your battery is at 73 percent and charging. You're sending 1.5 kilowatts to the grid."

## Supported Queries

- **Solar snapshot:** "How's my solar?", "Solar status"
- **Battery:** "Battery level", "Battery status"
- **Consumption:** "How much am I using?"
- **Grid:** "Am I exporting?", "Grid status"
- **Today:** "Solar today", "Today's production"
- **Health:** "System health", "Panel status"
