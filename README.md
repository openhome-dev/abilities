
<h1 align="center">OpenHome Abilities</h1>

<p align="center">
  <strong>Open-source voice AI plugins for OpenHome - build, share, and remix.</strong>
</p>

<p align="center">
  <a href="https://app.openhome.com">Dashboard</a> •
  <a href="https://docs.openhome.com">Docs</a> •
  <a href="https://discord.gg/openhome">Discord</a> 
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python" />
</p> 
<p align="center">
  <a href="https://github.com/openhome-dev/abilities/stargazers">
    <img src="https://img.shields.io/github/stars/openhome-dev/abilities?style=social" alt="Stars">
  </a>
  <a href="https://github.com/openhome-dev/abilities/network/members">
    <img src="https://img.shields.io/github/forks/openhome-dev/abilities?style=social" alt="Forks">
  </a>
  <a href="https://github.com/openhome-dev/abilities/graphs/contributors">
    <img src="https://img.shields.io/github/contributors/openhome-dev/abilities" alt="Contributors">
  </a>
  <a href="https://github.com/openhome-dev/abilities/issues">
    <img src="https://img.shields.io/github/issues/openhome-dev/abilities" alt="Issues">
  </a>
</p>
---

## What Are Abilities?

Abilities are **modular voice AI plugins** that extend what OpenHome Agents can do. They're triggered by spoken phrases and can do anything — call APIs, play audio, run quizzes, control devices, have multi-turn conversations.

Each Ability is just **one file**: `main.py` — your Python logic.

Write your code, zip it, upload it to OpenHome, set your trigger words in the dashboard, and your Agent can do something new.

---

## Quick Start — Your First Ability in 5 Minutes

**1. Pick a template**

```bash
git clone https://github.com/openhome-dev/abilities.git
cp -r abilities/templates/basic-template my-first-ability
```

**2. Edit `main.py`** — here's the simplest possible Ability:

```python
import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class MyFirstCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        await self.capability_worker.speak("Hi! Tell me what's on your mind.")
        user_input = await self.capability_worker.user_response()
        response = self.capability_worker.text_to_text_response(
            f"Give a short, helpful response to: {user_input}"
        )
        await self.capability_worker.speak(response)
        self.capability_worker.resume_normal_flow()
```

> **Note:** The `#{{register_capability}}` line is required boilerplate — copy it exactly. OpenHome handles the platform-managed `config.json` at runtime, so you never need to create or edit it.

**3. Upload to OpenHome**

- Zip your folder
- Go to [app.openhome.com](https://app.openhome.com) → Abilities → Add Custom Ability
- Upload the zip
- Set your **trigger words** in the dashboard (the phrases that activate your Ability)
- Test it in the Live Editor

**4. Trigger it** — Say one of your trigger words in a conversation and your Ability takes over.

📖 **Full guide:** [docs/getting-started.md](docs/getting-started.md)

---

## 🖥️ CLI — Build & Manage Abilities from Your Terminal

Prefer not to zip-and-upload by hand? The [`openhome` CLI](cli/README.md) links this
repo to your [app.openhome.com](https://app.openhome.com) account and does the whole
loop — **create, push, voice-test, edit/commit, sync, delete** — without the dashboard.

**Setup** (run from the repo root):
```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
cp .env.example .env        # add OPENHOME_API_KEY (from Settings → API Keys)
```
The API key alone is enough (sent as `X-API-KEY`); run `openhome` from anywhere.

**Core flow:**
```bash
openhome agents                                  # list your agents
openhome create my-weather -t api-template       # scaffold into user/ + auto-push to your account
#   …edit user/my-weather/main.py…
openhome push user/my-weather --commit -m "v2"   # update in place (keeps the same ability), commit a version
openhome call                                     # 🎙 real voice call (mic + speakers) to your default agent
openhome sync                                     # pull your account's abilities back into user/
openhome delete my-weather                        # remove from account + local folder
```

**Contribute to this repo** — promote a finished ability from your private `user/`
workspace into `community/` and open a PR:
```bash
openhome push_to_community my-weather            # copies user/my-weather → community/my-weather, validates it
```

Your personal abilities live in `user/` (gitignored); `push_to_community` is the
bridge from there into `community/` for a contribution. Full command reference and
the API contract: **[cli/README.md](cli/README.md)**.

---

## 🔷 Official Abilities

Maintained by the OpenHome team. Tested, stable, and supported.

| Ability | Description | Example Triggers | API Required | Docs |
|---------|-------------|------------------|--------------|------|
| [Audius Music DJ](official/audius-music-dj/) | Stream & DJ music from Audius | "play something on audius", "dj mode" | Audius | [README](official/audius-music-dj/README.md) |
| [Basic Advisor](official/basic-advisor/) | Daily life advice | "give me advice", "help me" | None | [README](official/basic-advisor/README.md) |
| [Date and Time](official/date-and-time/) | Current date & time info | "what time is it", "what's today's date" | None | [README](official/date-and-time/README.md) |
| [Music Player](official/music-player/) | Play music from URL or file | "play music", "play a song" | None | [README](official/music-player/README.md) |
| [Perplexity Web Search](official/perplexity-web-search/) | AI-powered web search | "search the web", "look this up" | Perplexity | [README](official/perplexity-web-search/README.md) |
| [Quiz Game](official/quiz-game/) | AI-generated trivia | "start a quiz", "quiz me" | None | [README](official/quiz-game/README.md) |
| [Sound Generator](official/sound-generator/) | AI sound effects | "make a sound", "create a sound" | ElevenLabs | [README](official/sound-generator/README.md) |
| [Weather](official/weather/) | Current weather by location | "what's the weather" | None | [README](official/weather/README.md) |

> **Trigger words** are configured in the OpenHome dashboard when you install an Ability, not in the code.

---

## 🔶 Community Abilities

Built by the community. Reviewed for security and SDK compliance before merging.

| Ability | Description | Example Triggers | API Required | Docs |
|---------|-------------|------------------|--------------|------|
| [Gmail Voice Assistant](https://github.com/openhome-dev/abilities/tree/dev/community/gmail-connector) | Manage Gmail by voice — list, read, reply, compose, archive, and mark as read | "check my email", "gmail", "send an email" | Google OAuth | [README](https://github.com/openhome-dev/abilities/blob/dev/community/gmail-connector/README.md) |
| [Google Calendar Assistant](https://github.com/openhome-dev/abilities/tree/dev/community/google-calendar) | Create, list, update, and delete Google Calendar events | "google calendar", "what's on my calendar", "schedule a meeting" | Google OAuth | [README](https://github.com/openhome-dev/abilities/blob/dev/community/google-calendar/README.md) |
| [Google Tasks Assistant](https://github.com/openhome-dev/abilities/tree/dev/community/google-tasks) | Add, view, complete, delete, and rename Google Tasks across task lists | "tasks", "todo", "add a task" | Google OAuth | [README](https://github.com/openhome-dev/abilities/blob/dev/community/google-tasks/README.md) |
| [Daily Morning Brief](https://github.com/openhome-dev/abilities/tree/dev/community/google-daily-brief) | Short morning brief covering weather, today's calendar, and unread emails | "daily brief", "morning brief", "start my day" | Google OAuth, Open-Meteo (keyless) | [README](https://github.com/openhome-dev/abilities/blob/dev/community/google-daily-brief/README.md) |
| [Podcast Player](https://github.com/openhome-dev/abilities/tree/dev/community/podcast-player) | Find and play podcast episodes by voice, including trending picks and guest search | "play a podcast", "podcast player", "play the latest <show>" | Listen Notes | [README](https://github.com/openhome-dev/abilities/blob/dev/community/podcast-player/README.md) |
| [Movie Recommender](https://github.com/openhome-dev/abilities/tree/dev/community/movie-recommender) | Discover movies by voice — recommendations, trending, ratings, and where to watch | "recommend a movie", "what should I watch", "trending movies" | TMDB | [README](https://github.com/openhome-dev/abilities/blob/dev/community/movie-recommender/README.md) |
| [Local Event Explorer](https://github.com/openhome-dev/abilities/tree/dev/community/local-event-explorer) | Find local concerts, comedy, festivals, and other things to do | "events", "find events", "event explorer" | Ticketmaster, Serper, SeatGeek | [README](https://github.com/openhome-dev/abilities/blob/dev/community/local-event-explorer/README.md) |
| *Your Ability here* | [Contribute one →](CONTRIBUTING.md) | | | |

> **Note:** Community Abilities are reviewed for security and SDK compliance. OpenHome does not guarantee ongoing maintenance. See [Contributing](CONTRIBUTING.md) for details.

---

## 📁 Starter Templates

Don't start from scratch — grab a template:

| Template | Best For | Pattern |
|----------|----------|---------|
| [Basic](templates/basic-template) | First-timers | Speak → Listen → Respond → Exit |
| [API](templates/api-template) | API integrations | Speak → Call API → Speak result → Exit |
| [Loop](templates/loop-template) | Interactive apps | Loop with listen → process → respond → exit command |
| [Openclaw](templates/OpenClaw) | OpenClaw integrations | OpenClaw-based ability scaffold |
| [OpenHome Local](templates/Local) | Local development | Run & test abilities locally |
| [ReadWriteFile](templates/ReadWriteFile) | File operations | Read from / write to files on device |
| [SendEmail](templates/SendEmail) | Email notifications | Compose & send emails programmatically |
| [Alarm](templates/Alarm) | Timers & alarms | Background mode: continuous monitoring loop |
| [Background](templates/Background) | Background monitoring | Auto-start → Monitor → Act → Sleep → Repeat (endless) |

---

## 🤝 Contributing

We welcome community Abilities! Here's the short version:

1. Fork this repo
2. Copy a template into `community/your-ability-name/`
3. Build your Ability
4. Open a Pull Request

**Full guide:** [CONTRIBUTING.md](CONTRIBUTING.md)

**First time?** Look for issues labeled [`good-first-issue`](../../labels/good-first-issue).

---

## 🏆 Community → Official Promotion

Exceptional community Abilities can be promoted to Official status. We look for:

- **Stability** — No critical bugs for 30+ days
- **Quality** — Clean code, good voice UX
- **Maintenance** — Author is responsive

When promoted, the Ability moves to `official/`, gets the blue badge on Marketplace, and the author is credited permanently. [Learn more →](docs/promotion.md)

---

## 📖 Documentation

| Doc | Description |
|-----|-------------|
| [Getting Started](docs/getting-started.md) | Build your first Ability in 5 minutes |
| [CapabilityWorker](docs/capability-worker.md) | Full SDK reference |
| [Patterns Cookbook](docs/patterns.md) | Common patterns with code examples |
| [Publishing to Marketplace](docs/publishing-to-marketplace.md) | How to ship your Ability to users |
| [Promotion Path](docs/promotion.md) | How community Abilities become official |
| [OpenHome SDK Reference](docs/OpenHome_SDK_Reference.md) | Complete guide to SDK
| [What Makes a Good Ability](docs/What_Makes_a_Good_Ability.md) | Guide to buil great OpenHome abilities
---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

All contributions to `community/` are licensed under the same terms. By submitting a PR, you agree to these terms. Original authorship is always credited.
