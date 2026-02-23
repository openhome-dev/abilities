# Sports Scores & Standings

Fetches live sports scores, recent results, upcoming games, and league standings using TheSportsDB free API.

## Triggers

- "sports scores"
- "game score"
- "who won"
- "sports update"
- "league standings"
- "next game"

## Features

- Recent results for any team (last 5 games)
- Upcoming fixtures (next 5 games)
- League standings/table
- Supports multiple sports: football, basketball, baseball, hockey, soccer, etc.
- Multi-turn conversation for checking multiple teams

## Setup

No API key required. Uses TheSportsDB free test API key.

## Example Usage

> "How did the Lakers do?"
> "When's the next Arsenal game?"
> "Show me the Premier League standings"
> "Who won the Yankees game?"

## How It Works

1. User mentions a team or asks about scores
2. Searches TheSportsDB for the team
3. Fetches recent results, upcoming fixtures, or standings based on intent
4. LLM summarizes the data in a conversational sports update
5. Offers to check another team

## API Reference

- TheSportsDB: https://www.thesportsdb.com/api.php
