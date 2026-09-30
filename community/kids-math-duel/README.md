# Kids Math Duel

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hasni1731996-lightgrey?style=flat-square)

A head-to-head voice math game for two players. Siblings, parent vs. child, or any two people in the room — ten questions, five each, 8 seconds on the clock, and a steal mechanic that keeps both players locked in the whole time.

## What Makes It Different

| | `vibe-trivia` | `spelling-bee-coach` | Kids Math Duel |
|---|---|---|---|
| Players | 1 | 1 | **2 (head-to-head)** |
| Question source | LLM-generated | Static word list | **Pure Python (no LLM per question)** |
| Steal mechanic | No | No | **Yes — wrong answer = opponent can steal** |
| Countdown timer | No | No | **Yes — 8-second soft countdown** |
| Target audience | General | General | **Kids and families** |
| Setup required | None | None | None |

## Trigger Phrases

- `math duel` / `maths duel`
- `math game` / `math challenge` / `math battle`
- `math quiz` / `maths quiz`
- `times tables game`
- `number duel`

## How It Works

1. **Setup** — Speaker collects two player names by voice, then asks difficulty
2. **10 rounds** — Players alternate: 5 questions each
3. **8-second soft timer** — Speaker says "Time's up!" if no answer arrives; no hard cutoff, next round starts when the player speaks
4. **Steal mechanic** — Wrong answer or timeout? The other player gets to steal the point
5. **Score after every round** — "Correct! 3 in a row! Score: Zara 4, Hassan 2."
6. **Post-game debrief** — LLM writes a fun 2-sentence summary
7. **Play again?** — Yes / no prompt, new difficulty if playing again

## Difficulty Levels

| Level | Operations | Number range |
|---|---|---|
| Easy | + and − | 1–20 |
| Medium | +, −, and × | 1–12 (times tables) |
| Hard | +, −, ×, and ÷ | 1–50 × and ÷ (whole numbers only) |

Division always produces a whole-number answer — no remainders.

## Example Session

> **"Math duel"**
> → "Math Duel! Two players, ten questions, winner takes all. Let's set it up."
> → "What's player one's name?" → "Zara" → "Player one is Zara, right?" → "Yes"
> → "What's player two's name?" → "Hassan" → confirmed
> → "Easy, medium, or hard?" → "Medium"
> → "Alright — Zara versus Hassan, medium difficulty. Ten questions, five each. Here we go!"
>
> → "Zara — What is 7 times 8?"
> *(Zara answers)* "56"
> → "Correct! Score: Zara 1, Hassan 0."
>
> → "Hassan — What is 9 times 6?"
> *(Hassan answers)* "63"
> → "The answer was 54. Zara — steal it! What is 9 times 6?"
> *(Zara answers)* "54"
> → "Steal! Zara grabs the point. Score: Zara 2, Hassan 0."
>
> *(10 questions later)*
> → "Game over! Zara wins 7 to 3!"
> → "Zara absolutely dominated — seven out of ten with a four-question streak. Hassan, better luck next time, but that steal attempt in round two showed real quick thinking!"
> → "Want to play again?"

## Setup

No API keys. No external services. Works entirely with the built-in LLM and OpenHome's persistent storage.

1. Upload this folder via the OpenHome Dashboard
2. Add the trigger phrases above
3. Gather two players and trigger

## Author

Muhammad Hassan
