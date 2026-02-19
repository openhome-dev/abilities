# Perplexity Web Search
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Reyad-lightgrey?style=flat-square)

## What It Does
Instantly searches the web for real-time answers using the Perplexity AI API (Sonar Pro).  
Just ask anything — "What's the weather in Tokyo?" or "Latest news on AI?" — and it returns a concise, spoken-friendly answer without symbols or jargon.

## Suggested Trigger Words
- search
- tell me about
- what is
- who is


## Setup
- Requires a **Perplexity AI API key** (available at https://www.perplexity.ai/settings/api).
- Replace the placeholder `YOUR_API_KEY` in `main.py` with your own key before using.

## How It Works
1. User triggers with "search" or a question (or similar)
2. Assistant immediately acknowledges: "Let me check that for you real quick"
3. Sends the query to Perplexity's Sonar Pro model
4. Gets a clean, concise answer back
5. Speaks the result aloud: "Here's what I found: ..."
6. Resumes normal conversation flow automatically

## Example Conversation

**User:** What's the capital of Australia?  
**AI:** Let me check that for you real quick...  
Here's what I found: The capital of Australia is Canberra, not Sydney as many people assume.

**User:** Latest news on SpaceX  
**AI:** Let me check that for you real quick...  
Here's what I found: SpaceX recently completed a successful Starship test flight, marking a major milestone in their Mars mission program.

