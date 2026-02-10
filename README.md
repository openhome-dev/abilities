<p align="center">
  <img src="assets/logo.png" alt="OpenHome" width="120" />
</p>

<h1 align="center">OpenHome Abilities</h1>

<p align="center">
  <strong>Open-source voice AI plugins for OpenHome — build, share, and remix.</strong>
</p>

<p align="center">
  <a href="https://app.openhome.com">Dashboard</a> •
  <a href="https://docs.openhome.com">Docs</a> •
  <a href="https://discord.gg/openhome">Discord</a> •
  <a href="https://app.openhome.com/marketplace">Marketplace</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python" />
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs Welcome" />
</p>

---

## What Are Abilities?

Abilities are **modular voice AI plugins** that extend what OpenHome Personalities can do. They're triggered by spoken phrases and can do anything — call APIs, play audio, run quizzes, control devices, have multi-turn conversations.

Each Ability is just **two files**:

```
my-ability/
├── main.py        ← Your Python logic
└── config.json    ← Name + trigger phrases
```

That's it. Write your logic, zip it, upload it to OpenHome, and your Personality can do something new.

---

## Quick Start — Your First Ability in 5 Minutes

**1. Pick a template**

```bash
git clone https://github.com/openhome-dev/abilities.git
cp -r abilities/templates/basic-template my-first-ability
```

**2. Edit `config.json`**

```json
{
  "unique_name": "my_first_ability",
  "matching_hotwords": ["help me out", "give me advice"]
}
```

**3. Edit `main.py`** — here's the simplest possible Ability:

```python
import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class MyFirstCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
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

**4. Upload to OpenHome**

- Zip your folder
- Go to [app.openhome.com](https://app.openhome.com) → Abilities → Add Custom Ability
- Upload the zip
- Test it in the Live Editor

**5. Trigger it** — Say one of your hotwords in a conversation and your Ability takes over.

📖 **Full guide:** [docs/getting-started.md](docs/getting-started.md)

---

## 🔷 Official Abilities

Maintained by the OpenHome team. Tested, stable, and supported.

| Ability | Description | Trigger Words | API Required | Docs |
|---------|-------------|---------------|--------------|------|
| [Basic Advisor](official/basic-advisor/) | Daily life advice | "give me advice", "help me" | None | [README](official/basic-advisor/README.md) |
| [Quiz Game](official/quiz-game/) | AI-generated trivia | "start a quiz", "quiz me" | None | [README](official/quiz-game/README.md) |
| [Sound Generator](official/sound-generator/) | AI sound effects | "make a sound", "create a sound" | ElevenLabs | [README](official/sound-generator/README.md) |
| [Weather](official/weather/) | Current weather by location | "what's the weather" | None | [README](official/weather/README.md) |
| [Music Player](official/music-player/) | Play music from URL or file | "play music", "play a song" | None | [README](official/music-player/README.md) |

---

## 🔶 Community Abilities

Built by the community. Reviewed for security and SDK compliance before merging.

| Ability | Description | Author | Trigger Words | API Required |
|---------|-------------|--------|---------------|--------------|
| *Your Ability here* | [Contribute one →](CONTRIBUTING.md) | | | |

> **Note:** Community Abilities are reviewed for security and SDK compliance. OpenHome does not guarantee ongoing maintenance. See [Contributing](CONTRIBUTING.md) for details.

---

## 📁 Starter Templates

Don't start from scratch — grab a template:

| Template | Best For | Pattern |
|----------|----------|---------|
| [basic-template](templates/basic-template/) | First-timers | Speak → Listen → Respond → Exit |
| [api-template](templates/api-template/) | API integrations | Speak → Call API → Speak result → Exit |
| [loop-template](templates/loop-template/) | Interactive apps | Loop with listen → process → respond → exit command |

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

- **Adoption** — 50+ installs on the Marketplace
- **Stability** — No critical bugs for 30+ days
- **Quality** — Clean code, good voice UX
- **Maintenance** — Author is responsive

When promoted, the Ability moves to `official/`, gets the blue badge on Marketplace, and the author is credited permanently. [Learn more →](docs/promotion.md)

---

## 📖 Documentation

| Doc | Description |
|-----|-------------|
| [Getting Started](docs/getting-started.md) | Build your first Ability in 5 minutes |
| [CapabilityWorker API](docs/capability-worker-api.md) | Full SDK reference |
| [Patterns Cookbook](docs/patterns.md) | Common patterns with code examples |
| [Publishing to Marketplace](docs/publishing-to-marketplace.md) | How to ship your Ability to users |
| [Promotion Path](docs/promotion.md) | How community Abilities become official |

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

All contributions to `community/` are licensed under the same terms. By submitting a PR, you agree to these terms. Original authorship is always credited.
