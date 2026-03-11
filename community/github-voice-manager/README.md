# GitHub Voice Manager

Voice-controlled GitHub workflow for developers. Check notifications, list pull requests, browse repo issues, and get a quick status summary — all hands-free.

## What It Does

- **Notifications** — "Do I have any GitHub notifications?" → lists unread notifications with option to mark all as read
- **My Pull Requests** — "Any open PRs?" → lists your open PRs across all repos
- **Repo Issues** — "What are the open issues on owner/repo?" → lists issues for a specific repo
- **Repo Pull Requests** — "Show PRs on owner/repo" → lists PRs for a specific repo
- **My Repos** — "List my repos" → shows your most recently active repositories
- **Quick Summary** — "GitHub status" → notification count + open PR count in one sentence

## Why It's Not Redundant

The LLM cannot access your private GitHub repositories, check your personal notifications, or query account-specific data. This Ability authenticates via the GitHub REST API with a Personal Access Token to perform real read operations on your account.

## API Required

**GitHub REST API** — free, no rate limit issues for personal use.

### Setup

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Generate a new token (classic) with scopes: `repo`, `notifications`, `read:user`
3. Paste the token into the `GITHUB_TOKEN` constant in `main.py`

## Features

- **Quick Mode vs Full Mode** — says "check my PRs" and gets a direct answer, or says "GitHub" to enter a full interactive session
- **Intent Classification** — uses the LLM to classify voice commands into the right handler
- **Persistence** — remembers your GitHub username and last-used repo across sessions
- **Natural Voice UX** — filler speech during API calls, idle detection, exit word handling
- **Trigger Context Awareness** — reads what the user said to decide quick vs full mode

## Example Triggers

```
github, pull requests, notifications, my repos, open issues,
check my PRs, any open PRs, github notifications, github status,
code review, what's on github
```

## Author

Saif-Ur-Rehman

## License

MIT