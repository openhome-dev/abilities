from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": "xxx",
            "client_secret": "xxx",
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    },
    scopes=SCOPES
)

credentials = flow.run_local_server(port=8080)

print(f"Access Token: {credentials.token}")
print(f"Refresh Token: {credentials.refresh_token}") # refresh token for main.py to use