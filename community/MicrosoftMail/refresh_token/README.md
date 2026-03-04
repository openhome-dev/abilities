# Get a Refresh Token for the Outlook Connector

## Why We Need This

The Outlook Connector (e.g. `main.py`) talks to Microsoft Graph to read and send email. Microsoft requires your app to prove who the user is and that they’ve granted permission.

- **Access token** – Short-lived; used for each API request. Expires after about an hour.
- **Refresh token** – Long-lived; used to get new access tokens without asking the user to sign in again.

This folder’s script, **`get_refresh_token.py`**, uses Microsoft’s **device flow** (no browser in the script): you run the script, open a URL in your browser, enter a code, sign in once, and the script prints a **refresh token**. You paste that token (and the same `CLIENT_ID`) into your Outlook Connector so it can get access tokens automatically.

Without a valid refresh token (or another way to get tokens), the connector cannot call Microsoft Graph.

---

## Prerequisites

- **Python** – [Download](https://www.python.org/downloads/). After installing, in a terminal run:
  ```bash
  python --version
  ```
  You should see a version number.

- **MSAL** – Microsoft Authentication Library:
  ```bash
  pip install msal
  ```

---

## Step 1 – Create an App in Microsoft Entra

1. Go to [https://entra.microsoft.com](https://entra.microsoft.com).
2. Sign in with your Microsoft account.
3. Open **Applications** → **App registrations**.
4. Click **New registration**.

---

## Step 2 – Register the App

- **Name:** Any name (e.g. “Outlook Connector”).
- **Supported account types:**  
  **Accounts in any organizational directory and personal Microsoft accounts**  
  (needed for outlook.com / live.com / hotmail.com).
- **Redirect URI:** Leave blank (device flow doesn’t use it).

Click **Register**.

---

## Step 3 – Copy the Client ID

On the app’s **Overview** page, copy the **Application (client) ID** (a long GUID). You’ll put this in `get_refresh_token.py` and in your Outlook Connector (`main.py`).

---

## Step 4 – Allow Public Client Flows

Device flow is a “public client” flow, so it must be enabled:

1. In the app registration, go to **Authentication**.
2. Under **Advanced settings**, set **Allow public client flows** to **Yes**.
3. Click **Save**.

---

## Step 5 – Add API Permissions (Mail + User)

The script requests Mail and User scopes so the refresh token can be used for reading/sending mail:

1. Go to **API permissions** → **Add a permission**.
2. Choose **Microsoft Graph** → **Delegated permissions**.
3. Add:
   - `User.Read`
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `Mail.Send`
4. Click **Add permissions**.

*(You do **not** add `offline_access` yourself; MSAL requests it when a refresh token is needed.)*

---

## Step 6 – Put Your Client ID in the Script

Open `get_refresh_token.py` and set:

```python
CLIENT_ID = "your-application-client-id-from-entra"
```

Use the same Client ID you copied in Step 3. Save the file.

---

## Step 7 – Run the Script

In a terminal, from the folder that contains `get_refresh_token.py`:

```bash
python get_refresh_token.py
```

---

## Step 8 – Complete Device Login in the Browser

The script will print something like:

```
To sign in, use a web browser to open https://microsoft.com/devicelogin and enter the code XXXX-XXXX to authenticate.
```

Do this:

1. Open [https://microsoft.com/devicelogin](https://microsoft.com/devicelogin) in your browser.
2. Enter the code shown in the terminal.
3. Sign in with your **personal** Microsoft account (outlook.com, live.com, hotmail.com).
4. When asked for permissions, click **Accept**.

---

## Step 9 – Copy the Refresh Token into Your Outlook Connector

After you sign in, the script prints:

- A short preview of the **access token** (short-lived; you don’t need to copy this).
- The full **refresh token** – copy this entire value.

In your Outlook Connector (`main.py` or equivalent), set:

- **CLIENT_ID** – Same value as in `get_refresh_token.py` (your app’s Client ID).
- **TENANT_ID** – Use `"consumers"` so it matches this script’s authority (personal Microsoft accounts).
- **REFRESH_TOKEN** – The long string you just copied.

Example:

```python
CLIENT_ID = "28b10d08-5223-4d0b-8a2e-a2d92b519e8e"   # your app’s Client ID
TENANT_ID = "consumers"   # personal Microsoft accounts (outlook.com, etc.)
REFRESH_TOKEN = "<paste the refresh token from get_refresh_token.py here>"
```

Your connector can then use this refresh token to obtain access tokens and call Microsoft Graph (e.g. read/send mail) without the user signing in again each time.

---

## Summary

| Step | What you do |
|------|------------------|
| 1–5  | Create an Entra app, enable public client flow, add Mail + User delegated permissions. |
| 6    | Set `CLIENT_ID` in `get_refresh_token.py`. |
| 7    | Run `python get_refresh_token.py`. |
| 8    | Open microsoft.com/devicelogin, enter the code, sign in, accept permissions. |
| 9    | Copy the printed refresh token (and same `CLIENT_ID`) into your Outlook Connector; set `TENANT_ID = "consumers"`. |

The refresh token is what the Outlook Connector needs to get new access tokens and talk to Microsoft Graph on behalf of the user.
