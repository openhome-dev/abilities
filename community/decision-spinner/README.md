# Decision Spinner

## Overview
A voice-activated decision wheel that helps users make choices. Comes with 8 default options (Yes, No, Maybe, Absolutely, No Way, Try Again, Ask Later, Go For It) or accepts custom options. Spins with dramatic buildup and delivers results with game-show host energy via LLM reactions.

## Core Features
- **Trigger Words:** "Spin the wheel," "Spin a wheel," "Make a decision," "Decide for me," "Should I," "Yes or no," "Spinner"
- **Default Options:** YES, NO, MAYBE, ABSOLUTELY, NO WAY, TRY AGAIN, ASK LATER, GO FOR IT
- **Custom Options:** Users provide their own choices separated by commas or "or" (e.g., "pizza, tacos, sushi" or "beach or mountains")
- **Dramatic Buildup:** Pause before revealing the result
- **Swap Options Mid-Session:** Provide new options at any time during the loop

## Technical Implementation
Uses `random.choice()` for fair selection. Parses custom options from comma-separated or "or"-separated input. LLM generates game-show host style reactions via `text_to_text_response()`. Supports option swapping within the spin loop.

## How Users Interact
Say a trigger phrase to start. Provide custom options or say "default" / "yes" to use the built-in wheel. ARI spins and announces the result with dramatic flair. Say "spin again" to re-spin, provide new options to change the wheel, or say "stop" to exit.

## Dependencies
- No external APIs or setup required
- Uses only Python standard library (`random`, `json`, `os`)
