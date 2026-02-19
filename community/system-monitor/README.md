# system monitor

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@StressTestor-lightgrey?style=flat-square)

## what it does

Voice-driven system health checks. Ask about CPU, memory, disk, battery, network, running processes, or uptime and get a plain english summary spoken back. No API keys, no cloud services, everything runs locally.

## suggested trigger words

- "check my system"
- "how's my computer"
- "system status"
- "check my computer"

## setup

Requires `psutil` to be installed:

```bash
pip install psutil
```

No API keys or external services needed. Everything runs on your machine.

## how it works

When triggered, the ability collects CPU usage, memory, disk space, battery status, network traffic, and top processes. It uses the LLM to summarize everything into a natural spoken overview, then enters a follow-up loop where you can ask for details on any specific metric.

Say "done" or "exit" at any point to leave.

## example conversation

> **User:** "check my system"
> **AI:** "Your system looks healthy. CPU is cruising at 12 percent with plenty of memory free. Disk is about half full with 230 gigs available."
> **User:** "what about processes"
> **AI:** "Chrome is your biggest resource hog right now at 8 percent CPU and 4 percent memory. Everything else is under 2 percent."
> **User:** "battery?"
> **AI:** "You're at 74 percent, plugged in and charging. Should be full in about 40 minutes."
> **User:** "done"
> **AI:** "Got it. Have a good one."

## supported metrics

| Metric | What it reports |
|--------|----------------|
| CPU | usage percent, core count, 1/5/15 min load averages |
| Memory | total, used, available RAM in GB, percent used |
| Disk | total, used, free space on root partition, percent used |
| Battery | charge percent, plugged in status, time remaining |
| Network | total bytes sent and received since boot |
| Processes | top 5 by CPU usage with memory percent |
| Uptime | time since last boot in days/hours/minutes |
