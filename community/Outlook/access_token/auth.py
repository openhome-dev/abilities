import msal

CLIENT_ID = "YOUR_CLIENT_ID_HERE"

AUTHORITY = "https://login.microsoftonline.com/consumers"

app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=AUTHORITY
)

# 2 delegated scopes
scopes = [
    "User.Read",
    "Calendars.ReadWrite"
]

flow = app.initiate_device_flow(scopes=scopes)

if "user_code" not in flow:
    print("Failed to create device flow")
    print(flow)
    exit()

print(flow["message"])

result = app.acquire_token_by_device_flow(flow)

if "access_token" in result:
    print("\nAccess token:\n")
    print(result["access_token"])
else:
    print("\nToken error:\n")
    print(result)
