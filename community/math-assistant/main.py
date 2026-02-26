import json
import math
import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class MathAssistantCapability(MatchingCapability):
    """
    A voice-enabled math assistant that uses LLM to parse natural language
    math requests and perform calculations.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    async def run(self):
        """Main entry point for the math assistant capability."""

        await self.capability_worker.speak(
            "Hello! I'm your math assistant. Ask me to calculate something, "
            "solve an equation, convert units, or roll dice. What would you like to do?"
        )

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input:
                await self.capability_worker.speak(
                    "I didn't catch that. Could you please repeat?"
                )
                continue

            # Check for exit commands
            if self._is_exit_command(user_input):
                await self.capability_worker.speak("Goodbye! Happy calculating!")
                self.capability_worker.resume_normal_flow()
                return

            # Use LLM to parse the math request
            parsed = self._parse_math_request(user_input)

            # Handle based on the parsed intent
            response = await self._handle_parsed_request(parsed, user_input)

            # Ask if they need more help
            follow_up = await self.capability_worker.run_io_loop(
                response + " Would you like help with anything else? Say 'no thanks' to exit."
            )

            if self._is_exit_command(follow_up):
                await self.capability_worker.speak("Goodbye! Happy calculating!")
                self.capability_worker.resume_normal_flow()
                return

    def _parse_math_request(self, user_input: str) -> dict:
        """Use LLM to parse the user's math request into structured data."""

        system_prompt = """You are a math parser. Extract the mathematical intent from user speech.
        
Respond ONLY with a JSON object in this exact format:
{
    "intent": "calculation|conversion|equation|percentage|sqrt|power|random|unknown",
    "numbers": [list of numbers found],
    "operation": "add|subtract|multiply|divide|convert|solve|percent|sqrt|power|roll|flip",
    "from_unit": "unit converting from (for conversions)",
    "to_unit": "unit converting to (for conversions)",
    "expression": "the mathematical expression to evaluate",
    "explanation": "brief explanation of what the user wants"
}

Examples:
- "what is 5 plus 3" → {"intent": "calculation", "numbers": [5, 3], "operation": "add", "expression": "5 + 3"}
- "convert 10 miles to kilometers" → {"intent": "conversion", "numbers": [10], "from_unit": "miles", "to_unit": "kilometers"}
- "solve 2x plus 5 equals 15" → {"intent": "equation", "numbers": [2, 5, 15], "operation": "solve", "expression": "2x + 5 = 15"}
- "roll a dice" → {"intent": "random", "operation": "roll", "explanation": "roll a 6-sided die"}
- "square root of 16" → {"intent": "sqrt", "numbers": [16], "operation": "sqrt"}
"""

        prompt = f"Parse this math request: '{user_input}'"

        try:
            response = self.capability_worker.text_to_text_response(
                prompt, system_prompt=system_prompt
            )

            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {"intent": "unknown", "explanation": "Could not parse request"}

        except Exception:
            return {"intent": "unknown", "explanation": "Parse error"}

    async def _handle_parsed_request(self, parsed: dict, original_input: str) -> str:
        """Handle the parsed math request based on intent."""

        intent = parsed.get("intent", "unknown")
        numbers = parsed.get("numbers", [])

        try:
            if intent == "calculation":
                return self._do_calculation(parsed, original_input)

            elif intent == "conversion":
                return self._do_conversion(parsed)

            elif intent == "equation":
                return self._do_equation(parsed)

            elif intent == "percentage":
                return self._do_percentage(parsed, original_input)

            elif intent == "sqrt":
                if numbers:
                    result = math.sqrt(numbers[0])
                    return f"The square root of {numbers[0]} is {result:.4f}."
                return "What number would you like the square root of?"

            elif intent == "power":
                return self._do_power(parsed)

            elif intent == "random":
                operation = parsed.get("operation", "")
                if operation == "roll":
                    result = random.randint(1, 6)
                    return f"You rolled a {result}."
                elif operation == "flip":
                    result = random.choice(["heads", "tails"])
                    return f"It's {result}!"
                elif len(numbers) >= 2:
                    result = random.randint(int(numbers[0]), int(numbers[1]))
                    return f"Your random number between {numbers[0]} and {numbers[1]} is {result}."
                else:
                    result = random.randint(1, 100)
                    return f"Your random number is {result}."

            else:
                # Fallback: ask LLM to help interpret
                return self._fallback_response(original_input)

        except Exception:
            return "I had trouble with that calculation. Could you try rephrasing?"

    def _do_calculation(self, parsed: dict, original_input: str) -> str:
        """Perform basic arithmetic calculation."""
        numbers = parsed.get("numbers", [])
        operation = parsed.get("operation", "")
        expression = parsed.get("expression", "")

        if len(numbers) >= 2:
            a, b = numbers[0], numbers[1]

            if operation == "add":
                result = a + b
                return f"{a} plus {b} equals {result}."
            elif operation == "subtract":
                result = a - b
                return f"{a} minus {b} equals {result}."
            elif operation == "multiply":
                result = a * b
                return f"{a} times {b} equals {result}."
            elif operation == "divide":
                if b == 0:
                    return "I can't divide by zero."
                result = a / b
                return f"{a} divided by {b} equals {result:.4f}."

        # Fallback to LLM for complex expressions
        system_prompt = "You are a calculator. Respond with ONLY the numerical answer, nothing else."
        prompt = f"Calculate: {expression or original_input}. Give only the number."

        try:
            result = self.capability_worker.text_to_text_response(prompt, system_prompt=system_prompt)
            # Clean up the result
            result = result.strip().replace(",", "")
            return f"The answer is {result}."
        except Exception:
            return "I couldn't calculate that. Try saying something like 'what is 5 plus 3'."

    def _do_conversion(self, parsed: dict) -> str:
        """Perform unit conversion."""
        numbers = parsed.get("numbers", [])
        from_unit = parsed.get("from_unit", "").lower()
        to_unit = parsed.get("to_unit", "").lower()

        if not numbers:
            return "What value would you like to convert?"

        value = numbers[0]

        # Length conversions
        if "mile" in from_unit and "kilometer" in to_unit:
            result = value * 1.60934
            return f"{value} miles is {result:.2f} kilometers."
        if "kilometer" in from_unit and "mile" in to_unit:
            result = value / 1.60934
            return f"{value} kilometers is {result:.2f} miles."
        if ("foot" in from_unit or "feet" in from_unit) and "meter" in to_unit:
            result = value * 0.3048
            return f"{value} feet is {result:.2f} meters."
        if "meter" in from_unit and ("foot" in to_unit or "feet" in to_unit):
            result = value / 0.3048
            return f"{value} meters is {result:.2f} feet."
        if "inch" in from_unit and "centimeter" in to_unit:
            result = value * 2.54
            return f"{value} inches is {result:.2f} centimeters."

        # Weight conversions
        if "pound" in from_unit and "kilogram" in to_unit:
            result = value * 0.453592
            return f"{value} pounds is {result:.2f} kilograms."
        if "kilogram" in from_unit and "pound" in to_unit:
            result = value / 0.453592
            return f"{value} kilograms is {result:.2f} pounds."

        # Temperature conversions
        if "fahrenheit" in from_unit and "celsius" in to_unit:
            result = (value - 32) * 5 / 9
            return f"{value} degrees Fahrenheit is {result:.1f} degrees Celsius."
        if "celsius" in from_unit and "fahrenheit" in to_unit:
            result = (value * 9 / 5) + 32
            return f"{value} degrees Celsius is {result:.1f} degrees Fahrenheit."

        return "I can convert between miles and kilometers, feet and meters, pounds and kilograms, and Fahrenheit and Celsius."

    def _do_equation(self, parsed: dict) -> str:
        """Solve simple linear equations."""
        numbers = parsed.get("numbers", [])
        parsed.get("expression", "")

        # Pattern: ax + b = c
        if len(numbers) >= 3:
            a, b, c = numbers[0], numbers[1], numbers[2]
            x = (c - b) / a
            if x == int(x):
                return f"x equals {int(x)}."
            return f"x equals {x:.4f}."

        # Pattern: x + b = c
        elif len(numbers) >= 2:
            b, c = numbers[0], numbers[1]
            x = c - b
            return f"x equals {int(x)}."

        return "I can solve simple equations like '2x plus 3 equals 7'. Could you rephrase your equation?"

    def _do_percentage(self, parsed: dict, original_input: str) -> str:
        """Calculate percentages."""
        numbers = parsed.get("numbers", [])

        if len(numbers) >= 2:
            a, b = numbers[0], numbers[1]

            # "What is X% of Y?"
            if "of" in original_input.lower():
                result = (a * b) / 100
                return f"{a}% of {b} is {result}."

            # "X is what percent of Y?"
            result = (a / b) * 100
            return f"{a} is {result:.2f}% of {b}."

        return "I can calculate percentages. Try saying 'what is 20 percent of 100'."

    def _do_power(self, parsed: dict) -> str:
        """Calculate powers."""
        numbers = parsed.get("numbers", [])

        if len(numbers) >= 2:
            base, exp = numbers[0], numbers[1]
            result = base ** exp
            return f"{base} to the power of {exp} is {result}."
        elif len(numbers) == 1:
            result = numbers[0] ** 2
            return f"{numbers[0]} squared is {result}."

        return "What number would you like to calculate a power for?"

    def _fallback_response(self, user_input: str) -> str:
        """Fallback: use LLM to generate a helpful response."""
        system_prompt = """You are a helpful math assistant. The user has asked something 
        you couldn't parse as a specific math operation. Help them understand what you can do 
        (calculations, conversions, equations, percentages, square roots, powers, dice rolls). 
        Keep your response friendly and under 2 sentences."""

        try:
            response = self.capability_worker.text_to_text_response(
                f"User said: {user_input}", system_prompt=system_prompt
            )
            return response
        except Exception:
            return "I can help with calculations, conversions, equations, percentages, and more. What would you like to calculate?"

    def _is_exit_command(self, text: str) -> bool:
        """Check if user wants to exit."""
        if not text:
            return False
        exit_words = [
            "no",
            "exit",
            "quit",
            "stop",
            "done",
            "goodbye",
            "bye",
            "thanks",
            "thank you",
            "no thanks",
            "that's all",
            "thats all",
        ]
        text_lower = text.lower().strip().rstrip(".!?")
        return text_lower in exit_words or any(word in text_lower for word in exit_words[:5])

    def call(self, worker: AgentWorker):
        """Initialize and start the capability."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
