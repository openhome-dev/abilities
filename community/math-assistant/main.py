import re
import math
import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class MathAssistantCapability(MatchingCapability):
    """
    A voice-enabled math assistant that can perform calculations,
    solve equations, convert units, and explain mathematical concepts.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    async def run(self):
        """Main entry point for the math assistant capability."""

        await self.capability_worker.speak(
            "Hello! I'm your math assistant. I can help with calculations, "
            "solve equations, convert units, or explain math concepts. "
            "What would you like to do?"
        )

        while True:
            user_input = await self.capability_worker.user_response()

            # Check for exit commands
            if self._is_exit_command(user_input):
                await self.capability_worker.speak("Goodbye! Happy calculating!")
                self.capability_worker.resume_normal_flow()
                return

            # Process the math request
            response = await self._process_math_request(user_input)

            # Ask if they need more help
            follow_up = await self.capability_worker.run_io_loop(
                response + " Would you like help with anything else? "
                "Say 'no' to exit."
            )

            if self._is_exit_command(follow_up):
                await self.capability_worker.speak("Goodbye! Happy calculating!")
                self.capability_worker.resume_normal_flow()
                return
            # Otherwise continue the loop with the follow-up as the next input

    async def _process_math_request(self, user_input: str) -> str:
        """Process different types of math requests."""

        user_lower = user_input.lower()

        # Unit conversion
        if any(
            word in user_lower
            for word in [
                "convert",
                "to",
                "in",
                "feet",
                "meters",
                "miles",
                "kilometers",
                "pounds",
                "kilograms",
            ]
        ):
            return await self._handle_conversion(user_input)

        # Equation solving
        if any(
            word in user_lower
            for word in ["solve", "equation", "find x", "what is x"]
        ):
            return await self._handle_equation(user_input)

        # Percentage calculations
        if any(word in user_lower for word in ["percent", "%", "percentage"]):
            return await self._handle_percentage(user_input)

        # Square root
        if any(word in user_lower for word in ["square root", "sqrt", "root of"]):
            return await self._handle_square_root(user_input)

        # Powers/exponents
        if any(
            word in user_lower for word in ["power", "squared", "cubed", "to the power"]
        ):
            return await self._handle_power(user_input)

        # Random number
        if any(word in user_lower for word in ["random", "dice", "coin", "flip"]):
            return await self._handle_random(user_input)

        # Basic calculation
        return await self._handle_calculation(user_input)

    async def _handle_calculation(self, expression: str) -> str:
        """Handle basic arithmetic calculations safely."""
        try:
            result = self._parse_and_calculate(expression)
            return f"The answer is {result}."
        except Exception:
            return (
                "I couldn't calculate that. Please try saying it differently, "
                "like 'what is 5 plus 3' or 'calculate 10 times 4'."
            )

    def _parse_and_calculate(self, expression: str):
        """Parse and calculate mathematical expressions safely."""
        # Clean up the expression
        cleaned = self._clean_expression(expression)

        # Extract numbers and operators
        # Handle multi-digit numbers and decimals
        tokens = re.findall(r"\d+\.?\d*|[+\-*/()]", cleaned.replace(" ", ""))

        if not tokens:
            raise ValueError("No valid tokens found")

        # Convert number tokens to floats
        parsed_tokens = []
        for token in tokens:
            if token in "+-*/()":
                parsed_tokens.append(token)
            else:
                parsed_tokens.append(float(token))

        # Evaluate using safe shunting yard algorithm
        return self._evaluate_tokens(parsed_tokens)

    def _evaluate_tokens(self, tokens):
        """Evaluate tokens using operator precedence (shunting yard)."""
        # Define operator precedence
        precedence = {"+": 1, "-": 1, "*": 2, "/": 2}

        output = []
        operators = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if isinstance(token, (int, float)):
                output.append(token)
            elif token == "(":
                operators.append(token)
            elif token == ")":
                while operators and operators[-1] != "(":
                    output.append(operators.pop())
                if operators and operators[-1] == "(":
                    operators.pop()  # Remove the '('
            elif token in precedence:
                while (
                    operators
                    and operators[-1] != "("
                    and operators[-1] in precedence
                    and precedence[operators[-1]] >= precedence[token]
                ):
                    output.append(operators.pop())
                operators.append(token)
            i += 1

        # Pop remaining operators
        while operators:
            output.append(operators.pop())

        # Evaluate postfix expression
        stack = []
        for token in output:
            if isinstance(token, (int, float)):
                stack.append(token)
            elif token in "+-*/":
                if len(stack) < 2:
                    raise ValueError("Invalid expression")
                b = stack.pop()
                a = stack.pop()
                if token == "+":
                    stack.append(a + b)
                elif token == "-":
                    stack.append(a - b)
                elif token == "*":
                    stack.append(a * b)
                elif token == "/":
                    if b == 0:
                        raise ValueError("Division by zero")
                    stack.append(a / b)

        if len(stack) != 1:
            raise ValueError("Invalid expression")

        result = stack[0]

        # Format result nicely
        if isinstance(result, float):
            if result.is_integer():
                return int(result)
            return round(result, 4)
        return result

    async def _handle_conversion(self, user_input: str) -> str:
        """Handle unit conversions."""
        try:
            # Extract number and units
            result = self._convert_units(user_input)
            return result
        except Exception:
            return (
                "I can convert between feet and meters, miles and kilometers, "
                "pounds and kilograms, Celsius and Fahrenheit, and more. "
                "What would you like to convert?"
            )

    async def _handle_equation(self, user_input: str) -> str:
        """Handle simple equation solving."""
        try:
            # Look for patterns like "2x + 3 = 7"
            result = self._solve_simple_equation(user_input)
            return result
        except Exception:
            return (
                "I can solve simple equations like '2x plus 3 equals 7' or "
                "'x minus 5 equals 10'. What equation would you like me to solve?"
            )

    async def _handle_percentage(self, user_input: str) -> str:
        """Handle percentage calculations."""
        try:
            result = self._calculate_percentage(user_input)
            return result
        except Exception:
            return (
                "I can calculate percentages like 'what is 20 percent of 100' "
                "or '50 is what percent of 200'. What would you like to know?"
            )

    async def _handle_square_root(self, user_input: str) -> str:
        """Handle square root calculations."""
        try:
            # Extract number
            numbers = re.findall(r"\d+", user_input)
            if numbers:
                num = float(numbers[0])
                result = math.sqrt(num)
                return f"The square root of {num} is {result:.4f}."
            else:
                return "What number would you like the square root of?"
        except Exception:
            return "I can find square roots. Just ask for the square root of any number."

    async def _handle_power(self, user_input: str) -> str:
        """Handle power/exponent calculations."""
        try:
            result = self._calculate_power(user_input)
            return result
        except Exception:
            return (
                "I can calculate powers. Try saying '2 to the power of 5' "
                "or 'what is 3 squared'."
            )

    async def _handle_random(self, user_input: str) -> str:
        """Handle random number generation."""
        user_lower = user_input.lower()

        if "dice" in user_lower or "die" in user_lower:
            result = random.randint(1, 6)
            return f"You rolled a {result}."

        if "coin" in user_lower or "flip" in user_lower:
            result = random.choice(["heads", "tails"])
            return f"It's {result}!"

        if "between" in user_lower:
            numbers = re.findall(r"\d+", user_input)
            if len(numbers) >= 2:
                low, high = int(numbers[0]), int(numbers[1])
                result = random.randint(low, high)
                return f"Your random number between {low} and {high} is {result}."

        # Default random number 1-100
        result = random.randint(1, 100)
        return f"Your random number is {result}."

    def _clean_expression(self, expression: str) -> str:
        """Clean up the expression for calculation."""
        # Replace words with symbols
        replacements = {
            "plus": "+",
            "minus": "-",
            "times": "*",
            "multiplied by": "*",
            "divided by": "/",
            "over": "/",
            "modulo": "%",
            "mod": "%",
        }

        result = expression.lower()
        for word, symbol in replacements.items():
            result = result.replace(word, symbol)

        # Remove any characters that aren't numbers, operators, or parentheses
        result = re.sub(r"[^0-9+\-*/().\s]", "", result)

        return result

    def _convert_units(self, user_input: str) -> str:
        """Handle unit conversions."""
        user_lower = user_input.lower()
        numbers = re.findall(r"\d+\.?\d*", user_input)

        if not numbers:
            return "What value would you like to convert?"

        value = float(numbers[0])

        # Length conversions
        if "mile" in user_lower and "kilometer" in user_lower:
            result = value * 1.60934
            return f"{value} miles is {result:.2f} kilometers."
        if "kilometer" in user_lower and "mile" in user_lower:
            result = value / 1.60934
            return f"{value} kilometers is {result:.2f} miles."
        if "foot" in user_lower or "feet" in user_lower:
            result = value * 0.3048
            return f"{value} feet is {result:.2f} meters."
        if "meter" in user_lower and "foot" in user_lower:
            result = value / 0.3048
            return f"{value} meters is {result:.2f} feet."
        if "inch" in user_lower:
            result = value * 2.54
            return f"{value} inches is {result:.2f} centimeters."

        # Weight conversions
        if "pound" in user_lower and "kilogram" in user_lower:
            result = value * 0.453592
            return f"{value} pounds is {result:.2f} kilograms."
        if "kilogram" in user_lower and "pound" in user_lower:
            result = value / 0.453592
            return f"{value} kilograms is {result:.2f} pounds."

        # Temperature conversions
        if "fahrenheit" in user_lower and "celsius" in user_lower:
            result = (value - 32) * 5 / 9
            return f"{value}°F is {result:.1f}°C."
        if "celsius" in user_lower and "fahrenheit" in user_lower:
            result = (value * 9 / 5) + 32
            return f"{value}°C is {result:.1f}°F."

        return (
            "I can convert between miles and kilometers, feet and meters, "
            "pounds and kilograms, and Fahrenheit and Celsius. "
            "What would you like to convert?"
        )

    def _solve_simple_equation(self, equation: str) -> str:
        """Solve simple linear equations like '2x + 3 = 7'."""
        try:
            # Remove spaces and convert to lowercase
            eq = equation.lower().replace(" ", "").replace("equals", "=")

            # Pattern: ax + b = c or ax - b = c
            match = re.search(r"(\d*)x([+-])(\d+)=(\d+)", eq)
            if match:
                a_str, op, b_str, c_str = match.groups()
                a = int(a_str) if a_str else 1
                b = int(b_str)
                c = int(c_str)

                if op == "+":
                    x = (c - b) / a
                else:
                    x = (c + b) / a

                if x == int(x):
                    return f"x equals {int(x)}."
                return f"x equals {x:.4f}."

            # Pattern: x + b = c or x - b = c
            match = re.search(r"x([+-])(\d+)=(\d+)", eq)
            if match:
                op, b, c = match.groups()
                b, c = int(b), int(c)
                if op == "+":
                    x = c - b
                else:
                    x = c + b
                return f"x equals {x}."

            return (
                "I can solve simple equations like '2x plus 3 equals 7' or "
                "'x minus 5 equals 10'. Could you rephrase your equation?"
            )
        except Exception:
            return (
                "I can solve simple linear equations. Try saying something like "
                "'solve 2x plus 3 equals 7'."
            )

    def _calculate_percentage(self, user_input: str) -> str:
        """Calculate percentages."""
        numbers = re.findall(r"\d+", user_input)
        user_lower = user_input.lower()

        if len(numbers) >= 2:
            a, b = int(numbers[0]), int(numbers[1])

            # "What is X% of Y?"
            if "of" in user_lower:
                result = (a * b) / 100
                return f"{a}% of {b} is {result}."

            # "X is what percent of Y?"
            if "is" in user_lower and "what" in user_lower:
                result = (a / b) * 100
                return f"{a} is {result:.2f}% of {b}."

        return (
            "I can calculate percentages. Try saying 'what is 20 percent of 100' "
            "or '50 is what percent of 200'."
        )

    def _calculate_power(self, user_input: str) -> str:
        """Calculate powers."""
        numbers = re.findall(r"\d+", user_input)
        user_lower = user_input.lower()

        if "squared" in user_lower and numbers:
            num = int(numbers[0])
            result = num**2
            return f"{num} squared is {result}."

        if "cubed" in user_lower and numbers:
            num = int(numbers[0])
            result = num**3
            return f"{num} cubed is {result}."

        if len(numbers) >= 2:
            base, exp = int(numbers[0]), int(numbers[1])
            result = base**exp
            return f"{base} to the power of {exp} is {result}."

        return (
            "I can calculate powers. Try saying 'what is 2 to the power of 5' "
            "or 'what is 3 squared'."
        )

    def _is_exit_command(self, text: str) -> bool:
        """Check if user wants to exit."""
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
        ]
        return (
            text.lower().strip() in exit_words
            or text.lower().strip().rstrip(".") in exit_words
        )

    def call(self, worker: AgentWorker):
        """Initialize and start the capability."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
