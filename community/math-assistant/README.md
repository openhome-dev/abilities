# Math Assistant

A voice-enabled math assistant for OpenHome that performs calculations, solves equations, converts units, and explains mathematical concepts.

## Description

Your personal voice-activated math tutor. Ask for calculations, conversions, equation solving, or random numbers - all hands-free!

## Example Triggers

- "calculate 5 plus 3"
- "what is 20 percent of 100"
- "convert 5 miles to kilometers"
- "solve 2x plus 3 equals 7"
- "what is the square root of 16"
- "roll a dice"
- "flip a coin"
- "what is 2 to the power of 5"

## Features

### Basic Calculations
- Addition, subtraction, multiplication, division
- Support for natural language: "plus", "minus", "times", "divided by"
- Constants: pi, e

### Unit Conversions
- Miles ↔ Kilometers
- Feet ↔ Meters
- Inches ↔ Centimeters
- Pounds ↔ Kilograms
- Fahrenheit ↔ Celsius

### Equation Solving
- Simple linear equations: "2x + 3 = 7"
- Finds value of x

### Percentages
- "What is X% of Y?"
- "X is what percent of Y?"

### Powers & Roots
- Square roots
- Cubes and squares
- Custom powers: "2 to the power of 5"

### Random Generation
- Roll dice (1-6)
- Flip coin (heads/tails)
- Random number between range
- Random number 1-100

## How to Use

1. Say a trigger phrase to activate
2. Ask your math question naturally
3. Get your answer spoken back
4. Continue with more math or say "no" to exit

## Example Conversations

**User:** "OpenHome, calculate 15 times 4"
**Assistant:** "The answer is 60. Would you like help with anything else?"

**User:** "Convert 68 degrees Fahrenheit to Celsius"
**Assistant:** "68°F is 20.0°C. Would you like help with anything else?"

**User:** "Solve 3x minus 5 equals 10"
**Assistant:** "x equals 5. Would you like help with anything else?"

**User:** "Roll a dice"
**Assistant:** "You rolled a 4. Would you like help with anything else?"

**User:** "No"
**Assistant:** "Goodbye! Happy calculating!"

## API Required

None - all calculations are performed locally using Python's math library.

## Notes

- Uses safe evaluation to prevent code injection
- Supports natural language math expressions
- Handles both spoken numbers and written numbers
- Graceful error handling with helpful suggestions
