# Calculator

Perform math calculations by voice. Understands both spoken numbers ("fifteen plus twenty-seven") and standard expressions ("15 + 27").

## Trigger Words

- "calculate"
- "calculator"
- "what is"
- "how much is"
- "math"
- "compute"
- "equals"
- "solve"
- "square root"
- "percent of"

## Supported Operations

| Operation | Example |
|-----------|---------|
| Addition | "fifteen plus twenty-seven" |
| Subtraction | "one hundred minus forty-two" |
| Multiplication | "six times seven" |
| Division | "eighty divided by four" |
| Powers | "two to the power of eight" |
| Square roots | "square root of one hundred and forty-four" |
| Percentages | "fifteen percent of two hundred" |
| Modulo | "seventeen mod five" |
| Trig / Math | sin, cos, tan, log, floor, ceil, abs, round |

## Usage

Say a trigger phrase like "calculator" or "what is", then speak your math problem.

## No Setup Required

No API keys or secrets needed. Uses Python's `ast` module for safe expression evaluation — no `eval()`.

## Author

[@Bradymck](https://github.com/Bradymck)
