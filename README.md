<a id="top"></a>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-FF4F15?style=flat-square&logo=opensourceinitiative&logoColor=white" alt="License" />
  <img src="https://img.shields.io/badge/Python-3.10+-56B9E7?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Abilities-100%2B-715CFF?style=flat-square" alt="Abilities" />
  <a href="https://github.com/openhome-dev/abilities/stargazers"><img src="https://img.shields.io/github/stars/openhome-dev/abilities?style=flat-square&logo=github&logoColor=white&color=060524" alt="Stars"></a>
  <a href="https://github.com/openhome-dev/abilities/network/members"><img src="https://img.shields.io/github/forks/openhome-dev/abilities?style=flat-square&logo=github&logoColor=white&color=060524" alt="Forks"></a>
  <a href="https://github.com/openhome-dev/abilities/graphs/contributors"><img src="https://img.shields.io/github/contributors/openhome-dev/abilities?style=flat-square&color=060524" alt="Contributors"></a>
  <a href="https://github.com/openhome-dev/abilities/issues"><img src="https://img.shields.io/github/issues/openhome-dev/abilities?style=flat-square&color=060524" alt="Issues"></a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/openhome-logo-dark.png">
    <img alt="OpenHome" src="assets/openhome-logo-light.png" width="220">
  </picture>
</p>

<h1 align="center">OpenHome Abilities</h1>

<h3 align="center">Open-source voice-AI plugins that give your OpenHome Agent new powers.</h3>

<p align="center"><b>Build, share, and remix.</b></p>

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" height="16" alt="Python" /> <b>Build an Agent plugin in Python</b> &nbsp;·&nbsp; 🎙️ <b>Test it with voice</b> &nbsp;·&nbsp; 🛍️ <b>Ship your Agent Skill to the Marketplace</b>
</p>

<p align="center">
  <a href="https://app.openhome.com"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20OpenHome%20Web%20App-FF4F15?style=for-the-badge&labelColor=FF4F15" alt="OpenHome Web App"></a>
  <a href="https://docs.openhome.com"><img src="https://img.shields.io/badge/Official%20OpenHome%20Docs-060524?style=for-the-badge&logo=readthedocs&logoColor=white&labelColor=060524" alt="Official OpenHome Docs"></a>
  <a href="https://docs.openhome.com/community/abilities"><img src="https://img.shields.io/badge/%F0%9F%9B%8D%EF%B8%8F%20Abilities%20Marketplace-715CFF?style=for-the-badge&labelColor=715CFF" alt="Abilities Marketplace"></a>
  <a href="https://discord.gg/openhome"><img src="https://img.shields.io/badge/Join%20our%20Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white&labelColor=5865F2" alt="Join our Discord Community"></a>
</p>

<br />

<table align="center">
  <tr>
    <td width="320" valign="top">
      ⭐ &nbsp;<a href="#official-abilities"><b>Official OpenHome Abilities</b></a><br />
      <sub>Team-maintained Abilities. Tested, stable, and supported.</sub>
    </td>
    <td width="320" valign="top">
      🧰 &nbsp;<a href="#templates"><b>Abilities Starter Templates</b></a><br />
      <sub>Minimal, working scaffolds to copy and build on.</sub>
    </td>
  </tr>
  <tr>
    <td width="320" valign="top">
      🌍 &nbsp;<a href="#community"><b>Community Contributed Abilities</b></a><br />
      <sub>Voice Abilities built and shared by the community.</sub>
    </td>
    <td width="320" valign="top">
      🤝 &nbsp;<a href="#contributing"><b>Contribution Guide</b></a><br />
      <sub>Build your own Ability and open a pull request.</sub>
    </td>
  </tr>
</table>

---

<a id="what-are-abilities"></a>

## 🧩 What Are Abilities?

An **Ability** is a Python plugin that extends your OpenHome Agent to do something the language model cannot do from a prompt alone, such as fetching data from the web, controlling a smart device, playing audio, remembering things across sessions, or running a multi-step voice workflow.

> The test: if the LLM can already answer it in conversation, it is not adding value as an Ability.

```
You speak a trigger word  ->  your Ability is triggered  ->  its flow runs  ->  the Agent responds
```

You write the logic. OpenHome handles speech-to-text, the LLM, text-to-speech, and routing. Most Abilities are a single file: `main.py`.

---

<a id="quick-reference"></a>

## 📖 Quick Reference

New to OpenHome? Here is the vocabulary in one place.

**Key terms**
| Term | What it means |
|------|---------------|
| **Agent** (Personality) | The voice assistant itself: an LLM, a voice, and a prompt. Every OpenHome speaker runs one, and it adapts to you as you talk. |
| **Ability** | A Python plugin that gives an Agent a new power (this repo). |
| **Trigger words** | The spoken phrases that activate an Ability, set in the dashboard. |
| **CapabilityWorker** | The SDK object an Ability uses for all input and output (speak, listen, call the LLM, store files). |
| **Marketplace** | Where the community shares Agents and Abilities: build in the dashboard, request to publish, and others install and review. |
| **DevKit** | OpenHome's hardware (a Raspberry Pi) that Local Abilities run on. |

**The four Ability types**
| Type | Triggered by | Lifecycle | Used for | Entry file(s) |
|------|--------------|-----------|----------|---------------|
| 🟦 **Skill** | A user trigger word | Runs once, then exits | Hotword-triggered tasks (the original pattern) | `main.py` |
| 🟪 **Agent Controlled** | The Agent decides | Runs on demand | Data lookups, tool use, delegated actions | `main.py` (in active development) |
| 🟧 **Background Daemon** | Auto-starts when a session begins | Loops until the session ends | Monitoring, alarms, ambient intelligence | `background.py` |
| 🟩 **Local** | A user trigger word | Runs on DevKit hardware | GPIO, sensors, and other on-device hardware | `main.py` + `devkit_functions.py` |

---

<a id="build"></a>

## 🚀 Build Your First Ability

You only need to edit one file. Here is the whole loop.

**1. Pick a template**
```bash
git clone https://github.com/openhome-dev/abilities.git
cp -r abilities/templates/basic-template my-first-ability
```

**2. Edit `main.py`** (this is a complete, working Ability)
```python
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class MyFirstCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}          # required boilerplate, copy exactly

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        await self.capability_worker.speak("Hi! What's on your mind?")
        user_input = await self.capability_worker.user_response()
        reply = self.capability_worker.text_to_text_response(
            f"Give a short, helpful response to: {user_input}"
        )
        await self.capability_worker.speak(reply)
        self.capability_worker.resume_normal_flow()   # always call this on exit
```

> Two rules that matter most: keep the `#{{register capability}}` tag exactly as written, and call `resume_normal_flow()` on every exit path or the speaker stays silent. OpenHome manages the platform-level `config.json` at runtime, so you never create or edit it.

**3. Upload it**
- Zip your folder.
- Go to [app.openhome.com](https://app.openhome.com), then Abilities, then Add Custom Ability.
- Upload the zip.

**4. Set your trigger words** in the dashboard (the phrases that activate your Ability).

**5. Test it** in the Live Editor, then say a trigger word in a conversation.

> Prefer the terminal? Once you are comfortable, the [OpenHome CLI](#cli) does this whole loop (create, voice-test, push) without zipping or uploading by hand.

📖 Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

---

<a id="templates"></a>

## 🧰 Abilities Starter Templates

Do not start from a blank file. Each template is a minimal, working scaffold for one [Ability type](#quick-reference); together they cover all four types, so you can start from the pattern closest to what you are building. Copy one and build on top of it.

**🟦 Skill** (runs once on a trigger word)
| Template | Teaches | Entry |
|----------|---------|-------|
| [Basic Template](templates/basic-template) | The minimal Speak, Listen, Respond, Exit loop | `main.py` |
| [API Template](templates/api-template) | Fetch from an external API and speak the result | `main.py` |
| [Loop Template](templates/loop-template) | Multi-turn conversation until an exit phrase | `main.py` |
| [Wikipedia](templates/wikipedia) | Answer "what is" questions with a short Wikipedia summary, no key needed | `main.py` |
| [Slack Assistant](templates/slack-assistant) | Slack by voice: channels, messages, DMs, and people search | `main.py` |
| [Send Email](templates/send-email) | Send email with attachments via `send_email()` | `main.py` |
| [Read Write File](templates/read-write-file) | Persist data across sessions with file storage | `main.py` |
| [OpenClaw](templates/openclaw) | Drive a local computer through OpenClaw | `main.py` |
| [OpenHome Local Link](templates/openhome-local-link) | Turn speech into shell commands on a local machine | `main.py` |

**🟩 Local** (runs on real DevKit hardware)
| Template | Teaches | Entry |
|----------|---------|-------|
| [Philips Hue Light Control](templates/philips-hue-light-control) | Control a Hue bulb over Bluetooth, no bridge needed | `main.py` + `devkit_functions.py` |
| [DevKit LED Lights Control](templates/devkit-led-lights-control) | Voice-control the DevKit's onboard NeoPixel ring | `main.py` + `devkit_functions.py` |
| [Camera Feed](templates/camera-feed) | Look at the DevKit's live camera feed and answer questions about it | `main.py` + `devkit_functions.py` |
| [DevKit Stats](templates/devkit-stats) | Report live DevKit telemetry by voice: CPU, memory, temperature, uptime | `main.py` + `devkit_functions.py` |

**🟧 Background Daemon** (auto-runs and loops for the whole session)
| Template | Teaches | Entry |
|----------|---------|-------|
| [Background Daemon](templates/background-daemon) | A continuous monitor loop | `background.py` |
| [Alarm](templates/alarm) | A Skill and a daemon working together via shared files | `main.py` + `background.py` |

> Agent Controlled Abilities are written like a Skill (`main.py`); the Agent decides when to run them, with no trigger word. See [Quick Reference](#quick-reference).

> More detail on each template: [templates/README.md](templates/README.md)

---

<a id="official-abilities"></a>

## ⭐ Official OpenHome Abilities

Maintained by the OpenHome team. Tested, stable, and supported. Install any of these from the dashboard, or read the source to learn the patterns.

| Ability | What it does | Try saying | API key |
|---------|--------------|------------|---------|
| [Audius Music DJ](official/audius-music-dj/) | Stream and DJ music from Audius | _"play something on audius"_ | Audius |
| [Basic Advisor](official/basic-advisor/) | Daily life advice | _"give me advice"_ | None |
| [Date and Time](official/date-and-time/) | Current date and time | _"what time is it"_ | None |
| [Music Player](official/music-player/) | Play music from a URL or file | _"play a song"_ | None |
| [Perplexity Web Search](official/perplexity-web-search/) | AI-powered web search | _"search the web"_ | Perplexity |
| [Quiz Game](official/quiz-game/) | AI-generated trivia | _"start a quiz"_ | None |
| [Sound Generator](official/sound-generator/) | AI sound effects | _"make a sound"_ | ElevenLabs |
| [Weather](official/weather/) | Current weather by location | _"what's the weather"_ | None |

> Trigger words are set in the dashboard when you install an Ability, not in the code.

---

<a id="community"></a>

## 🌍 Community Contributed Abilities

Built by the community and featured on the [Marketplace](https://docs.openhome.com/community/abilities). Each Ability is reviewed for security and SDK compliance before it is merged.

| Ability | What it does | Try saying | API key |
|---------|--------------|------------|---------|
| [Daily Morning Brief](community/google-daily-brief/) | Weather, today's calendar, and unread Gmail in one briefing | _"morning brief"_ | Google |
| [Gmail Voice Assistant](community/gmail-connector/) | List, read, compose, reply, and archive Gmail by voice | _"check my email"_ | Google |
| [Google Calendar Assistant](community/google-calendar/) | Create, list, update, and delete calendar events | _"what's on my calendar"_ | Google |
| [Google Tasks Assistant](community/google-tasks/) | Add, view, complete, and rename tasks across lists | _"add a task"_ | Google |
| [Events Explorer](community/local-event-explorer/) | Find concerts, comedy, sports, festivals, and meetups | _"find events this weekend"_ | Ticketmaster, Serper, SeatGeek |
| [Ambient Sounds](community/noise-machine/) | Stream rain, ocean, cafe, fire, and white-noise ambience | _"play rain"_ | Freesound |
| [Movie Recommender](community/movie-recommender/) | Recommendations, trending, ratings, and where to watch | _"recommend a movie"_ | TMDB |
| [Podcast Player](community/podcast-player/) | Find and play podcast episodes, trending picks, guest search | _"play a podcast"_ | Listen Notes |
| [Adventure Planner](community/micro-adventure-planner/) | Plan a trip: itinerary, events, weather, budget, Notion export | _"one week in Barcelona"_ | Optional (Serper, Notion) |
| [Hacker News Digest](community/hn-digest/) | A voice digest of the HN front page plus topic deep-dives | _"what's on Hacker News"_ | None |
| [Spelling Bee Coach](https://docs.openhome.com/community/abilities/spelling-bee) | Spell words aloud, drill the misses, track accuracy over time | _"spelling bee"_ | None |

<p align="right"><sub><a href="community/">Browse all community Abilities &rarr;</a></sub></p>

> Want yours featured here? See the [Contribution Guide](#contributing).

---

<a id="cli"></a>

## ⌨️ OpenHome CLI

Once you are comfortable, the `openhome` CLI runs the whole build loop from your terminal: create, voice-test, push, and contribute, with no zipping or manual uploads.

**Setup** (from the repo root)
```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
cp .env.example .env          # add your OPENHOME_API_KEY (Settings, then API Keys)
```
Your API key alone is enough (sent as `X-API-KEY`), and `openhome` then runs from anywhere. For `openhome call` you also need an audio player: on macOS `brew install mpv portaudio`, on Linux `sudo apt install mpv portaudio19-dev`.

**The loop**
```bash
openhome agents                               # list your agents
openhome create my-skill -t basic-template    # scaffold into user/ and push to your account
#   ...edit user/my-skill/main.py...
openhome push user/my-skill --commit -m "v2"  # update the ability in place, commit a version
openhome call                                 # real mic and speaker voice test
openhome sync                                 # pull your account's abilities back into user/
openhome delete my-skill                      # remove from account and local folder
```

**Contribute from the CLI.** Your personal Abilities live in `user/` (gitignored). Promote a finished one into `community/` and open a PR:
```bash
openhome push_to_community my-skill           # copy user/my-skill into community/, then validate
```

Full command reference and the API contract: [cli/README.md](cli/README.md).

---

<a id="contributing"></a>

## 🤝 Contribution Guide

We welcome community Abilities. The short version:

1. Fork this repo.
2. Copy a template into `community/your-ability-name/`.
3. Build your Ability (`main.py` plus `README.md`).
4. Validate it: `python3 validate_ability.py community/your-ability-name`.
5. Open a Pull Request against the `dev` branch.

First time? Look for [`good-first-issue`](../../labels/good-first-issue). Full guide: [CONTRIBUTING.md](CONTRIBUTING.md). Also: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [SECURITY.md](SECURITY.md).

---

<a id="contributors"></a>

## 🌟 Contributors

Built by an incredible community. Thank you to everyone who has shipped an Ability or improved the project.

<p align="center">
  <a href="https://github.com/Rizwan-095"><img src="https://avatars.githubusercontent.com/u/93827753?v=4&s=64" width="56" height="56" alt="Rizwan-095" /></a>
  <a href="https://github.com/uzair401"><img src="https://avatars.githubusercontent.com/u/64142661?v=4&s=64" width="56" height="56" alt="uzair401" /></a>
  <a href="https://github.com/Husnain-Bhatti"><img src="https://avatars.githubusercontent.com/u/74509896?v=4&s=64" width="56" height="56" alt="Husnain-Bhatti" /></a>
  <a href="https://github.com/hassan1731996"><img src="https://avatars.githubusercontent.com/u/99031061?v=4&s=64" width="56" height="56" alt="hassan1731996" /></a>
  <a href="https://github.com/chrisgbiz"><img src="https://avatars.githubusercontent.com/u/25496457?v=4&s=64" width="56" height="56" alt="chrisgbiz" /></a>
  <a href="https://github.com/megz2020"><img src="https://avatars.githubusercontent.com/u/24996542?v=4&s=64" width="56" height="56" alt="megz2020" /></a>
  <a href="https://github.com/Kaushal-205"><img src="https://avatars.githubusercontent.com/u/64428589?v=4&s=64" width="56" height="56" alt="Kaushal-205" /></a>
  <a href="https://github.com/abubakar4360"><img src="https://avatars.githubusercontent.com/u/73287161?v=4&s=64" width="56" height="56" alt="abubakar4360" /></a>
  <a href="https://github.com/samsonadmasu"><img src="https://avatars.githubusercontent.com/u/44081691?v=4&s=64" width="56" height="56" alt="samsonadmasu" /></a>
  <a href="https://github.com/ArturKozhushnyi"><img src="https://avatars.githubusercontent.com/u/137943726?v=4&s=64" width="56" height="56" alt="ArturKozhushnyi" /></a>
  <a href="https://github.com/yonaseth12"><img src="https://avatars.githubusercontent.com/u/88596815?v=4&s=64" width="56" height="56" alt="yonaseth12" /></a>
  <a href="https://github.com/RyanBhandal"><img src="https://avatars.githubusercontent.com/u/152874150?v=4&s=64" width="56" height="56" alt="RyanBhandal" /></a>
  <a href="https://github.com/fiction17"><img src="https://avatars.githubusercontent.com/u/43264627?v=4&s=64" width="56" height="56" alt="fiction17" /></a>
  <a href="https://github.com/Ju-usc"><img src="https://avatars.githubusercontent.com/u/112113286?v=4&s=64" width="56" height="56" alt="Ju-usc" /></a>
  <a href="https://github.com/BhargavTelu"><img src="https://avatars.githubusercontent.com/u/145568338?v=4&s=64" width="56" height="56" alt="BhargavTelu" /></a>
  <a href="https://github.com/ammyyou112"><img src="https://avatars.githubusercontent.com/u/19497106?v=4&s=64" width="56" height="56" alt="ammyyou112" /></a>
  <a href="https://github.com/Akio9090-dev"><img src="https://avatars.githubusercontent.com/u/216783405?v=4&s=64" width="56" height="56" alt="Akio9090-dev" /></a>
  <a href="https://github.com/zainirfan13"><img src="https://avatars.githubusercontent.com/u/48196604?v=4&s=64" width="56" height="56" alt="zainirfan13" /></a>
  <a href="https://github.com/harmsolo13"><img src="https://avatars.githubusercontent.com/u/238943697?v=4&s=64" width="56" height="56" alt="harmsolo13" /></a>
  <a href="https://github.com/engrumair842-arch"><img src="https://avatars.githubusercontent.com/u/234150436?v=4&s=64" width="56" height="56" alt="engrumair842-arch" /></a>
  <a href="https://github.com/alimujtaba478"><img src="https://avatars.githubusercontent.com/u/70099666?v=4&s=64" width="56" height="56" alt="alimujtaba478" /></a>
  <a href="https://github.com/BILLKISHORE"><img src="https://avatars.githubusercontent.com/u/181403793?v=4&s=64" width="56" height="56" alt="BILLKISHORE" /></a>
  <a href="https://github.com/francip"><img src="https://avatars.githubusercontent.com/u/49422?v=4&s=64" width="56" height="56" alt="francip" /></a>
  <a href="https://github.com/pipinstallshan"><img src="https://avatars.githubusercontent.com/u/96914475?v=4&s=64" width="56" height="56" alt="pipinstallshan" /></a>
  <a href="https://github.com/FHLiang221"><img src="https://avatars.githubusercontent.com/u/145803225?v=4&s=64" width="56" height="56" alt="FHLiang221" /></a>
  <a href="https://github.com/melodygui"><img src="https://avatars.githubusercontent.com/u/122416115?v=4&s=64" width="56" height="56" alt="melodygui" /></a>
  <a href="https://github.com/uchebuzz-coder"><img src="https://avatars.githubusercontent.com/u/233603053?v=4&s=64" width="56" height="56" alt="uchebuzz-coder" /></a>
  <a href="https://github.com/sterling-prog"><img src="https://avatars.githubusercontent.com/u/261519752?v=4&s=64" width="56" height="56" alt="sterling-prog" /></a>
  <a href="https://github.com/jibzus"><img src="https://avatars.githubusercontent.com/u/28382334?v=4&s=64" width="56" height="56" alt="jibzus" /></a>
  <a href="https://github.com/codeforstartups"><img src="https://avatars.githubusercontent.com/u/48567820?v=4&s=64" width="56" height="56" alt="codeforstartups" /></a>
  <a href="https://github.com/SpkArtZen"><img src="https://avatars.githubusercontent.com/u/146536119?v=4&s=64" width="56" height="56" alt="SpkArtZen" /></a>
  <a href="https://github.com/saifrehman100"><img src="https://avatars.githubusercontent.com/u/98314783?v=4&s=64" width="56" height="56" alt="saifrehman100" /></a>
  <a href="https://github.com/Rizwan-algoryc"><img src="https://avatars.githubusercontent.com/u/258008242?v=4&s=64" width="56" height="56" alt="Rizwan-algoryc" /></a>
  <a href="https://github.com/rawqubit"><img src="https://avatars.githubusercontent.com/u/4531201?v=4&s=64" width="56" height="56" alt="rawqubit" /></a>
  <a href="https://github.com/Mmiless"><img src="https://avatars.githubusercontent.com/u/126657986?v=4&s=64" width="56" height="56" alt="Mmiless" /></a>
  <a href="https://github.com/mahsumaktas"><img src="https://avatars.githubusercontent.com/u/28611322?v=4&s=64" width="56" height="56" alt="mahsumaktas" /></a>
  <a href="https://github.com/MKmuneebkhalid"><img src="https://avatars.githubusercontent.com/u/91009156?v=4&s=64" width="56" height="56" alt="MKmuneebkhalid" /></a>
  <a href="https://github.com/Kuberwastaken"><img src="https://avatars.githubusercontent.com/u/97027230?v=4&s=64" width="56" height="56" alt="Kuberwastaken" /></a>
  <a href="https://github.com/StressTestor"><img src="https://avatars.githubusercontent.com/u/212606152?v=4&s=64" width="56" height="56" alt="StressTestor" /></a>
  <a href="https://github.com/code-guru1"><img src="https://avatars.githubusercontent.com/u/5417404?v=4&s=64" width="56" height="56" alt="code-guru1" /></a>
  <a href="https://github.com/chadnewbry"><img src="https://avatars.githubusercontent.com/u/5430767?v=4&s=64" width="56" height="56" alt="chadnewbry" /></a>
  <a href="https://github.com/cedarscarlett"><img src="https://avatars.githubusercontent.com/u/247856479?v=4&s=64" width="56" height="56" alt="cedarscarlett" /></a>
  <a href="https://github.com/brianchilders"><img src="https://avatars.githubusercontent.com/u/1120465?v=4&s=64" width="56" height="56" alt="brianchilders" /></a>
  <a href="https://github.com/azazrashid"><img src="https://avatars.githubusercontent.com/u/75885216?v=4&s=64" width="56" height="56" alt="azazrashid" /></a>
  <a href="https://github.com/crunchdomo"><img src="https://avatars.githubusercontent.com/u/55187002?v=4&s=64" width="56" height="56" alt="crunchdomo" /></a>
</p>

<p align="center"><sub>Want to contribute? <a href="#contributing">Start here</a>.</sub></p>

---

## 🏆 Community to Official

Exceptional community Abilities can be promoted to Official status. We look for:

- **Stability**, no critical bugs for 30 or more days.
- **Quality**, clean code and great voice UX.
- **Maintenance**, a responsive author.

When promoted, the Ability moves to `official/`, gets the official badge on the Marketplace, and the author is credited permanently. [Learn more](docs/promotion.md).

---

<a id="documentation"></a>

## 📚 Official OpenHome Docs

**Get started**
- [Getting Started](docs/getting-started.md), your first Ability in 5 minutes
- [Patterns Cookbook](docs/patterns.md), common patterns with code

**SDK reference**
- [OpenHome SDK Reference](docs/OpenHome_SDK_Reference.md), the complete SDK (source of truth)
- [CapabilityWorker](docs/capability-worker.md), the I/O object every Ability uses

**Design and advanced**
- [What Makes a Good Ability](docs/What_Makes_a_Good_Ability.md)
- [Designing OpenHome Abilities](docs/Designing_OpenHome_Abilities.md)
- [Agent Memory and Context Injection](docs/Agent-Memory-and-Context-Injection.md)
- [Agent-Controlled Abilities](docs/Agent_Controlled_Abilities.md)

**Ship it**
- [Publishing to Marketplace](docs/publishing-to-marketplace.md)
- [Promotion Path](docs/promotion.md)

---

## 📜 License

Licensed under the [MIT License](LICENSE). All contributions to `community/` are licensed under the same terms. By submitting a PR you agree to these terms, and original authorship is always credited.

<p align="center"><sub><a href="#top">Back to top</a></sub></p>
