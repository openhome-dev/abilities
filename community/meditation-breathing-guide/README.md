# Meditation & Breathing Guide

A voice-guided breathing exercise and meditation ability for the OpenHome platform. Supports box breathing, 4-7-8 breathing, and LLM-generated guided meditations with timed pauses.

## Triggers

- "meditation"
- "breathing exercise"
- "breathe"
- "mindfulness"
- "calm down"
- "relax"

## Features

- **Box Breathing:** 4-count in, hold, out, hold cycles
- **4-7-8 Breathing:** Breathe in 4, hold 7, out 8 — great for calming the nervous system
- **Guided Meditation:** LLM-generated calming prompts with timed pauses
- Configurable duration (2, 5, or 10 minutes)
- Cycle counting and session completion summary

## Setup

No API keys required. This ability uses the built-in LLM for guided meditation generation and timed pauses via `session_tasks.sleep()`.

## Example Usage

> "I need to relax"
> "Box breathing"
> "5 minutes"

## How It Works

1. Offers breathing technique choices
2. Asks for preferred duration
3. Guides the user through timed breathing cycles or meditation segments
4. Announces session completion with cycle count
