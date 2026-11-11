# MCP Bridge

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

## What It Does
Connect your speaker to any MCP server you choose, then use its tools by voice. You add the server's address (and a token, if it needs one) in Settings. MCP Bridge asks the server which tools it has, picks the right one for what you say, fills in the details, and speaks back a short answer. No tool needs its own setup.

One Zapier MCP server is enough to reach thousands of apps (Gmail, Sheets, Trello, Slack and more). Documentation and developer servers work too.

## Suggested Trigger Words
- "MCP bridge"
- "use my MCP"
- "ask my server"
- "use my tools"
- "Zapier"

## Setup
1. Pick an MCP server that is reachable on the public internet over HTTPS.
2. Go to **Settings, then API Keys**:
   - `mcp_server_url` (required): the server's MCP endpoint, for example `https://mcp.zapier.com/api/v1/connect`.
   - `mcp_server_token` (optional): the server's token. MCP Bridge sends it as `Authorization: Bearer <token>`. Leave it empty for servers that need no key.
3. Say a trigger word.

**Zapier:** create a server at mcp.zapier.com, add the actions you want, and generate a connection token (Zapier shows it only once). Put the endpoint in `mcp_server_url` and the token in `mcp_server_token`. Don't put the token in the URL.

**Servers to try with no key:**
- `https://docs.mcp.cloudflare.com/mcp` (search Cloudflare's docs)
- `https://mcp.deepwiki.com/mcp` (ask about any public GitHub repo)

## How It Works
| You say | MCP Bridge does |
|---|---|
| "MCP bridge" | Connects and says which server it reached. |
| "What can it do?" | Reads the tool names three at a time and offers more. |
| "What does add card do?" | Reads that tool's own short description. |
| "Search the docs for the Workers request limit" | Picks the tool, fills in the details, calls it and gives you a short spoken summary. |
| "Add 'call the plumber' to my Trello board" | Asks for anything required that's missing, all in one question ("I need the title and list"), with one follow-up at most for whatever is still missing. Then it says what it's about to do and asks "Go ahead, or change something?". You can say yes, no, or what to change. |
| "Add a card due tomorrow" | Knows today's date in your timezone, so "tomorrow" or "next Friday" become real dates. |

The session stays open after each answer, so you can keep going. Say "done", "that's all", "forget it" or "I'm all set" at any prompt to stop.

### What it reuses instead of asking
MCP Bridge reads what OpenHome and your other abilities already know, so it can fill details like "my city" or "send it to my sister" without asking:

| Source | Owner | What's used |
|---|---|---|
| `user_profile.md`, `user_summary.md` | OpenHome platform | Facts about you, such as your name |
| `memory_mirror_corrections.md` | Memory Mirror | Facts you've confirmed or corrected |
| `social_memory.json` | Social Memory | Names of people you know and how you know them. Its private context notes are skipped |
| `get_region_data()` | OpenHome | Your current area |
| `get_timezone()` | OpenHome | Today's date and time for relative dates (falls back to UTC) |

These are only read, never written. They're held in memory for the session only, used only when your request points to you or someone you know, and never logged. Any value taken from them always goes through the spoken confirmation, even for read-only tools, because it's about to leave for a third-party server. The confirmation names it ("Using Islamabad from what I know"), but never reads out an email address or a long number. If none of these exist, everything still works and MCP Bridge simply asks.

### Which tools run without asking
A tool runs straight away only when **all three** are true:
- The server marks it read-only (`readOnlyHint: true`) and doesn't mark it destructive.
- Neither its name nor the start of its description has a write word such as send, create, add, update, delete, pay, book, cancel, publish or run.
- None of its values came from your stored details (see above).

Everything else asks for confirmation first. That includes any tool the server hasn't marked at all, such as DeepWiki's tools and most Zapier actions. Tools that aren't marked read-only also get a "this might not be undoable" warning, unless the server explicitly marks them non-destructive. MCP treats unmarked tools as possibly destructive.

### Safety and privacy
- **Untrusted server content.** Tool descriptions and tool output come from a third party. They are passed to the language model as clearly marked data, with instructions never to follow anything written inside them. MCP Bridge makes exactly one tool call per request you make, and output from one call never triggers another.
- **Address checks.** Only `https://` addresses are accepted. Redirects are never followed. Addresses on private, local or cloud-metadata networks are refused as typed.
- **Limits on replies.** Replies are capped at 512 KB. Only the first 6,000 characters are summarized.
- **Spoken output.** Answers are plain spoken English, at most two sentences and under 30 words, with no links, lists or markdown. Email addresses, phone numbers and long ids are never read out.
- **What's stored.** One Context Storage key, `mcp_bridge_state`, holds a short fingerprint of the server address (a hash, without any query string), whether the server uses the new or older MCP protocol, and the server's display name. Tokens, tool lists and tool output are never stored. Logs show the server address without its query string and never show the token.

### Protocol support
- **MCP 2026-07-28 (stateless Streamable HTTP):** each call is one POST with the `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers. Non-ASCII names use the spec's base64 header form, and parameters marked `x-mcp-header` are mirrored into `Mcp-Param-*` headers. Tools with invalid `x-mcp-header` markings are skipped, as the spec requires.
- **Older servers (2025-03-26 to 2025-11-25):** detected automatically by the spec's fallback rules, then used with the `initialize` handshake and `Mcp-Session-Id`. If the session expires, it re-connects once.
- **Reply formats:** JSON or an SSE stream.
- **Tool lists:** fetched once per session, following pagination up to 200 tools. With more than 40 tools, a first pass narrows the list before a tool is chosen.

### Limits
- **No OAuth-only servers.** Signing in needs a browser, which a voice ability can't do. Servers must accept a token, or no auth at all.
- **Public servers only.** The ability runs in OpenHome's cloud, so servers on your home network or `localhost` can't be reached.
- **One server at a time.**
- **Not supported:**
  - the deprecated 2024-11-05 HTTP+SSE transport
  - tools that ask follow-up questions mid-call (`input_required`)
  - long-running task tools
  - change subscriptions
- **Images and audio.** If a tool returns them, MCP Bridge says it got them but can't share them here.
- **Timeouts.** A tool call times out after 30 seconds. Real servers usually answer in 5 to 10 seconds, so MCP Bridge says a short filler first ("Checking with Zapier", then varied ones like "One sec").

### How it differs from existing options
- **n8n Commander:** you build and wire a webhook for each workflow. MCP Bridge finds the server's tools on its own, through the MCP standard.
- **The API template:** one hardcoded endpoint per ability. MCP Bridge needs no code per service.
- **OpenClaw, Hermes, Local Link templates and Voice Dev Terminal:** these need software running on your own computer. MCP Bridge talks to a hosted server directly.
- **Slack Voice Operator, Gmail, GitHub and the other single-service abilities:** each covers one service. MCP Bridge covers whatever your server exposes.

## Example Conversation
> **User:** MCP bridge
>
> **OpenHome:** Connected to Zapier. What do you need?
>
> **User:** Add "call the plumber" to my Trello board
>
> **OpenHome:** What list should I use?
>
> **User:** To do
>
> **OpenHome:** I'll add a card called "call the plumber" to your To Do list. This might not be undoable. Go ahead, or change something?
>
> **User:** Make it the Doing list instead
>
> **OpenHome:** I'll add a card called "call the plumber" to your Doing list. This might not be undoable. Go ahead, or change something?
>
> **User:** Yes
>
> **OpenHome:** Checking with Zapier.
>
> **OpenHome:** Done, the card "call the plumber" is on your Doing list. Anything else?
>
> **User:** That's all
>
> **OpenHome:** Okay, done for now.
