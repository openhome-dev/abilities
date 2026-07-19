# Hermes Ability for OpenHome

Talk to your local **Hermes Agent** (Nous Research) through an OpenHome voice
device. Ask out loud; Hermes answers using its tools, memory, and skills, and
replies in natural spoken language.

```
You speak  ->  OpenHome  ->  OpenHome Local Link (openhome CLI, your PC)  ->  Hermes Agent
                        spoken reply travels back along the same path
```

The **OpenHome Local Link** gateway runs on your PC via the `openhome` CLI. It
stays connected to your Agent and routes each request to whichever local handler
is available — including **Hermes** when it's installed. This ability sends its
requests over Local Link and speaks back the reply.

---

## How it works

**The ability** (installed from the Marketplace) takes your request — if you only
said the wake word, it asks what you'd like to do first. Before sending anything
it confirms destructive requests (those containing `rm -rf`, or `sudo` / `kill` /
`killall` / `pkill`) with you. It then pings Local Link to confirm it's
connected, runs a discovery call to confirm `hermes` is one of the detected
handlers, forwards your request, and speaks the reply. It keeps looping for
follow-up questions (no wake word needed) until you say an exit word such as
`stop`, `done`, `goodbye`, or `never mind`.

**OpenHome Local Link** is the `openhome local` gateway running on your computer.
It routes each incoming request to a local handler:

- **local-link** — a raw shell executor. Always available.
- **hermes** — used when Hermes is installed and configured.
- **openclaw** — used when OpenClaw is installed and its gateway is running.

The gateway auto-detects which handlers are ready and reports them to the Agent,
which is how this ability's discovery check finds `hermes`.

---

## Setup

### 1. Install Hermes

Install the Hermes Agent from Nous Research
(<https://github.com/nousresearch/hermes-agent>) and configure it with an LLM API
key. Verify the CLI is on your PATH:

```bash
hermes --version
```

If that prints a version, Local Link will detect Hermes as a handler.

### 2. Install and log in to the OpenHome CLI

The Local Link gateway ships with the OpenHome CLI. Install it from the repo
(requires Python 3.10 or newer):

```bash
git clone https://github.com/openhome-dev/abilities.git
cd abilities
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
cp .env.example .env

# Log in with your OpenHome API key (Dashboard -> Settings -> API Keys)
openhome login
```

Full CLI setup (JWT, command reference):
<https://docs.openhome.com/guides/getting-started/cli>

### 3. Start OpenHome Local Link

Run the gateway on the same machine where Hermes is installed, and keep it
running:

```bash
openhome local start        # start the gateway in the background
openhome local status       # confirm it's running and Hermes was detected
openhome local logs         # stream requests and replies live (Ctrl-C to stop)
openhome local stop         # stop it
```

`openhome local run` runs it in the foreground for debugging. `start` and `run`
accept `--client-id` (device name, default `laptop`), `--role` (default `agent`),
and `--timeout` (per-request seconds, default `30`). Give each device a distinct
`--client-id` if you run more than one.

### 4. Install the ability (OpenHome dashboard)

Open the Dashboard, go to the **Marketplace**, add the **Hermes** template, set
**Trigger Words** (for example `hermes` or `ask hermes`), and enable it on your
agent. You can edit it anytime in the **Live Editor**.

---

## Using it

> **"Hermes."** then *"Sending your inquiry to Hermes, one moment."* (if you
> didn't include a question, it asks what you'd like to ask first)
> **"What's my disk usage?"** then *"Your main drive is about 72 percent full,
> with roughly 64 gigabytes free."*
> **"That's all, thanks."** then *"Exiting now."*

Follow-up questions don't need the wake word; the loop keeps listening until you
say an exit word.

---

## Troubleshooting

- **"OpenHome Local Link isn't connected":** the gateway isn't running. Start it
  with `openhome local start`, then check `openhome local status`. If you're
  logged out, run `openhome login` first.
- **"Hermes isn't available on your computer":** Local Link is connected but
  didn't detect the Hermes handler. Confirm `hermes --version` works, then
  restart the gateway (`openhome local stop && openhome local start`).
- **Requests time out or lose the connection:** raise the per-request timeout,
  e.g. `openhome local run --timeout 120`, and watch `openhome local logs`.
- **Tool calls hang waiting for approval:** configure Hermes to auto-approve
  tool calls (its non-interactive / `--yolo` mode) so it can run unattended for
  voice. Enable that knowingly.
- **Won't connect to OpenHome:** wrong or expired API key. Re-run `openhome
  login` with a fresh key from Dashboard -> Settings -> API Keys.

## Security

Local Link runs Hermes with **your** permissions (shell and files), so only
trigger requests you'd run yourself. This ability confirms destructive-looking
requests (`rm -rf`, `sudo`, `kill`) before sending them, but that's a safety net,
not a guarantee. Auto-approving Hermes tool calls removes the manual approval
step — use it knowingly. Keep your OpenHome API key secret and rotate it if
exposed.
