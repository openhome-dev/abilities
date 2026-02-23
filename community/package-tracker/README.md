# Package Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

## What It Does

Tracks real parcel shipments by tracking number. You say a tracking number (and optionally the carrier, e.g. USPS or FedEx), and the ability calls the TrackingMore API and speaks the current status, last location, and route. This is **real external integration** — the LLM cannot look up live tracking data on its own.

## Suggested Trigger Words

- track my package
- package tracking
- where is my package
- check tracking
- shipment status
- track parcel
- tracking number

## Setup

- Get a **TrackingMore API key** (free tier available): sign up at [trackingmore.com](https://www.trackingmore.com/signup.html) and create an API key in the dashboard.
- In `main.py`, replace `YOUR_TRACKINGMORE_API_KEY` with your key for local testing.
- **Before submitting a PR**, replace the real key with the placeholder again (as per OpenHome rules).

## How It Works

1. User triggers with a phrase like "track my package".
2. Ability asks for the tracking number (and optionally carrier: USPS, FedEx, UPS, DHL, etc.).
3. User says the number, e.g. "9 4 1 0 8 1 1 2 3 4 5 6 7 8 9 0" or "1Z999AA10123456784".
4. Ability calls the TrackingMore API and speaks status, last location, and origin/destination.
5. User can ask for another tracking number or say "stop" / "exit" to leave.

## Example Conversation

**User:** Track my package  
**AI:** Package tracker here. Say a tracking number to check status, or say stop to exit.

**User:** 94055112062101234567890  
**AI:** Checking usps tracking for 94055112062101234567890... Status: In transit. Last location: Chicago. From United States to United States.

**User:** stop  
**AI:** Exiting package tracker. Goodbye.

## Technical Notes

- Uses `session_tasks.sleep()` (no `asyncio.sleep()`).
- Logging via `editor_logging_handler` (no `print()`).
- `resume_normal_flow()` is called on every exit path (in a `finally` block).
- All external requests use a `timeout` (10 seconds).
