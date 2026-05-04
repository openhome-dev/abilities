# Garmin Health Summary
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Local Link](https://img.shields.io/badge/Requires-Local%20Link-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12+-green?style=flat-square)

Ask your OpenHome agent for a spoken summary of your latest Garmin fitness data — last activity, heart rate, body battery, and sleep score — pulled live from your machine via Local Link.

## What It Does

- Fetches your latest Garmin Connect data on demand
- Summarizes it in a natural, conversational spoken response
- Pulls last activity (name, type, distance, duration, heart rate, calories)
- Also supports resting heart rate, body battery, and sleep score when synced

## Example

> **User:** "How did my last workout go?"
> **Agent:** "Your last activity was a walk in Los Angeles — about 3.2 miles in just over three hours. Your average heart rate was 102 and you burned around 392 calories."

## Requirements

- OpenHome agent with **Local Link** set up and running
- A Garmin Connect account
- Python 3.12+ on your local machine
- `garminconnect` Python library

## Setup

### Step 1: Install the garminconnect library

On your local machine, in a Python 3.12+ environment:

```bash
pip install garminconnect
```

### Step 2: Configure garmin_fetch.py

Open `garmin_fetch.py` and fill in your Garmin credentials:

```python
EMAIL = "your@email.com"
PASSWORD = "yourpassword"
```

Test it manually first to confirm it works:

```bash
python3 garmin_fetch.py
```

You should see a JSON response with your latest activity data. On first run it will authenticate and cache tokens to `~/.garminconnect` — subsequent runs will reuse those tokens.

### Step 3: Configure main.py

Open `main.py` and set the two path constants at the top:

```python
GARMIN_FETCH_SCRIPT = "REPLACE WITH ABSOLUTE PATH TO garmin_fetch.py"
PYTHON_PATH = "REPLACE WITH PATH TO YOUR PYTHON (e.g. /usr/bin/python3 or your venv python)"
```

For example:
```python
GARMIN_FETCH_SCRIPT = "/Users/yourname/garmin-health-summary/garmin_fetch.py"
PYTHON_PATH = "/Users/yourname/.venv/bin/python3"
```

### Step 4: Set up Local Link

1. Download and configure `local_client.py` from the [Local Link template](../../templates/Local)
2. Run it in a terminal — keep it running while using this ability:

```bash
source .venv/bin/activate
python3 local_client.py
```

### Step 5: Upload to OpenHome

1. Zip the `garmin-health-summary/` folder (only `main.py` is needed for upload)
2. Go to [OpenHome Dashboard](https://app.openhome.com) → Abilities → Add Custom Ability
3. Upload the zip
4. Set trigger words in the dashboard (see suggestions below)
5. Test in the Live Editor

## Suggested Trigger Words

- "garmin"
- "my stats"
- "how did my workout go"
- "health summary"
- "body battery"

## How It Works

1. User speaks a trigger phrase
2. Ability calls `exec_local_command` to run `garmin_fetch.py` on your machine via Local Link
3. The script authenticates with Garmin Connect and fetches your latest data
4. The raw JSON is passed to an LLM with a voice-optimized system prompt
5. The LLM converts the data into a natural spoken summary
6. Agent speaks the result

## Troubleshooting

**"Let me check your Garmin data." and then nothing**
Your Local Link client isn't running. Make sure `local_client.py` is active in a terminal.

**429 rate limit errors in logs**
Garmin is throttling repeated logins. This is normal on first run — the library tries multiple auth strategies. Once tokens are cached in `~/.garminconnect`, subsequent runs skip login entirely and the 429s go away.

**All values are null / None**
Your watch hasn't synced to Garmin Connect yet. Open the Garmin Connect app on your phone and force a sync, then try again. Heart rate and body battery in particular can lag behind by several minutes.

**ModuleNotFoundError: No module named 'garminconnect'**
The Local Link client is running under a different Python than the one where you installed garminconnect. Make sure `PYTHON_PATH` in `main.py` points to the Python that has the library installed, and that you activated the right virtual environment before running the client.

**SSL certificate error when starting local client**
Run the client inside your virtual environment rather than with system Python:
```bash
source .venv/bin/activate
python3 local_client.py
```
