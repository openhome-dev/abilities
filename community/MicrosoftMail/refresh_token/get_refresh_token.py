"""
Get a refresh token for the Outlook Connector (main.py).
Uses the same MSAL device flow as auth.py but requests Mail scopes + offline_access
so the response includes a refresh_token you can paste into the main script.

Usage:
  1. Set CLIENT_ID below (same as in your main script / app registration).
  2. pip install msal
  3. python get_refresh_token.py
  4. Open the URL, sign in with your personal Microsoft account, enter the code.
  5. Copy the refresh_token (and optionally CLIENT_ID) into main.py.
     In main.py use TENANT_ID = "consumers" to match this script's authority.
"""

import msal

CLIENT_ID = "YOUR_CLIENT_ID"

# Personal Microsoft accounts (outlook.com, live.com, hotmail.com)
AUTHORITY = "https://login.microsoftonline.com/consumers"

app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
)

# Mail.Read, Mail.ReadWrite, and Mail.Send are what the Outlook Connector needs.
# Do not add offline_access — MSAL reserves it and adds it when needed for refresh_token.
scopes = [
    "User.Read",
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
]

flow = app.initiate_device_flow(scopes=scopes)

if "user_code" not in flow:
    print("Failed to create device flow")
    print(flow)
    exit(1)

print(flow["message"])
print()

result = app.acquire_token_by_device_flow(flow)

if "access_token" in result:
    print("\n--- Success ---\n")
    print("Access token (short-lived):")
    print(result["access_token"][:80] + "...")
    if "refresh_token" in result:
        print("\nRefresh token (use this in main.py):")
        print(result["refresh_token"])
        print("\nIn your Outlook Connector main.py set:")
        print('  TENANT_ID = "consumers"  # same authority as this script')
        print('  REFRESH_TOKEN = "<paste the refresh token above>"')
    else:
        print("\nNo refresh_token in result. Ensure offline_access is in scopes.")
else:
    print("\nToken error:")
    print(result.get("error_description", result))
