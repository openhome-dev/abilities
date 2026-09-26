# Voice Claim Checker

Real-time fact-checking for anything you hear. Speak a claim — get a calibrated verdict with probability scores from Jev AI's System One model, synthesized into a natural spoken response.

## What makes it different

Every other voice assistant gives you an LLM opinion that hedges and guesses. This ability uses Jev AI's structured evaluation model, which returns calibrated probabilities — not generated text. It evaluates four dimensions simultaneously (factual support, misleading framing, evidence strength, overall verdict) and delivers a concise spoken summary you can actually trust.

## Trigger phrases

- "Fact check vaccines cause autism"
- "Is this true — coffee causes cancer?"
- "Check this claim: the Great Wall of China is visible from space"
- "Is that accurate? They said inflation is at a 40-year high"
- "Debunk this: humans only use 10 percent of their brains"
- "Verify this — the average person swallows eight spiders a year"
- "True or false: lightning never strikes the same place twice"

## Setup

Add your Jev AI API key under the name `jev_api_key` in your API settings. Free account at [jev-ai.pro](https://jev-ai.pro) includes welcome credits.

## Example session

> **User:** Fact check — the Great Wall of China is visible from space with the naked eye.
>
> **OpenHome:** Checking that...
>
> **OpenHome:** Refuted — factual support sits at 18%, and the evidence against this is strong consensus-level. The wall is far too narrow to see from low Earth orbit without aid. Misleading framing is low here; this is a straightforward myth.
>
> **OpenHome:** Want to check another one?
>
> **User:** Yes — is it true that humans only use 10 percent of their brains?
>
> **OpenHome:** Checking that...
>
> **OpenHome:** Refuted at 94% confidence. Neuroscience consensus is clear — brain imaging shows activity across virtually all regions. Evidence strength is at consensus level. This one's been debunked thoroughly.
>
> **OpenHome:** Want to check another one?
>
> **User:** No, that's all.
>
> **OpenHome:** Got it. Stay skeptical.

## What gets stored

The last 5 checked claims with their verdicts, accessible across sessions.

## API used

- **Jev AI System One** — `POST https://jev-ai.pro/api/v1/systemone` — structured probabilistic evaluation (noul, choice, score)
- **OpenHome LLM** — synthesizes Jev's structured output into natural spoken verdicts
