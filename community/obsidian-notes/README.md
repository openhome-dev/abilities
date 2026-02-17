# Obsidian Notes

## Overview
Voice-controlled access to an Obsidian vault. Search, read, create notes, and recall active context (long-term memory/priorities) through a Vercel API proxy backed by a GitHub-synced vault. Designed as a long-term memory layer for voice assistants.

## Core Features
- **Trigger Words:** "Check my notes," "Search my notes," "Obsidian," "Find a note," "Take a note," "Save a note," "My vault," "What did I write about," "What am I working on," "My priorities," "My context," "What's my focus," "Recall my memory"
- **Context Recall:** Pull active-context.md for current priorities, focus, and working memory
- **Search:** Full-text search across all vault notes
- **Read:** Read and summarize any note (long notes auto-summarized for voice)
- **Create:** Save new voice notes to the vault's inbox folder
- **LLM Intent Classification:** Automatically routes user requests to search, read, create, or context actions

## Setup
Set the `OBSIDIAN_VAULT_API` environment variable to your Vercel API endpoint:
```
OBSIDIAN_VAULT_API=https://your-app.vercel.app/api/vault
```

The Vercel endpoint proxies to a private GitHub repo containing the vault. Vault changes auto-commit and push via a file watcher hook.

### Backend Requirements
1. An Obsidian vault synced to a private GitHub repository
2. A Vercel serverless function (`/api/vault`) that reads from the GitHub API
3. A `GITHUB_TOKEN` environment variable on Vercel with repo read/write access
4. A file watcher (e.g., `fswatch`) that auto-commits and pushes vault changes

## Technical Implementation
Uses `requests` library to call the Vercel vault API. LLM classifies intent (search/read/create/context) via `text_to_text_response()`. Search extracts keywords from natural language before querying. Read tries search-first then direct path. Long notes (>500 chars) are auto-summarized for voice output.

## How Users Interact
Say a trigger phrase to start. Ask "what am I working on?" for context recall, "search for AquaPrime" to find notes, "read the consciousness doc" to hear a summary, or "save a note" to dictate a new one. Say "stop" to exit.

## Dependencies
- `requests` library (for HTTP calls to Vercel API)
- Vercel serverless function with GitHub API access
- GitHub-synced Obsidian vault
