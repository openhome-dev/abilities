import re
import math
import ast

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


def words_to_expression(text: str) -> str:
    t = text.lower().strip()
    for filler in ["what is", "how much is", "calculate", "compute", "solve", "equals", "the answer to", "what's"]:
        t = t.replace(filler, "")
    word_nums = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
        "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
        "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
        "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
        "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
        "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
        "million": "1000000",
    }
    for word, num in word_nums.items():
        t = re.sub(rf"\b{word}\b", num, t)
    t = re.sub(r"\bplus\b|\badded to\b", "+", t)
    t = re.sub(r"\bminus\b|\bsubtracted from\b|\btake away\b", "-", t)
    t = re.sub(r"\btimes\b|\bmultiplied by\b", "*", t)
    t = re.sub(r"\bdivided by\b|\bover\b|\bdivide\b", "/", t)
    t = re.sub(r"\bto the power of\b|\braised to\b", "**", t)
    t = re.sub(r"\bmod\b|\bmodulo\b", "%", t)
    t = re.sub(r"square root of\s*([\d.]+)", r"sqrt(\1)", t)
    t = re.sub(r"sqrt\s+([\d.]+)", r"sqrt(\1)", t)
    t = re.sub(r"([\d.]+)\s*percent of\s*([\d.]+)", lambda m: f"{float(m.group(1))/100}*{m.group(2)}", t)
    return t.strip()


SAFE_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "floor": math.floor, "ceil": math.ceil,
    "abs": abs, "round": round, "pi": math.pi, "e": math.e,
}


def ast_calc(node):
    """Recursively evaluate an AST node — only safe math ops allowed."""
    if isinstance(node, ast.Expression):
        return ast_calc(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Non-numeric constant")
    if isinstance(node, ast.BinOp):
        left = ast_calc(node.left)
        right = ast_calc(node.right)
        ops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.Pow: lambda a, b: a ** b,
            ast.Mod: lambda a, b: a % b,
            ast.FloorDiv: lambda a, b: a // b,
        }
        op_fn = ops.get(type(node.op))
        if op_fn is None:
            raise ValueError("Unsupported operator")
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = ast_calc(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("Unsupported unary operator")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only named functions allowed")
        fn = SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"Unknown function: {node.func.id}")
        args = [ast_calc(a) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        val = SAFE_FUNCS.get(node.id)
        if val is None:
            raise ValueError(f"Unknown name: {node.id}")
        return val
    raise ValueError(f"Unsupported node: {type(node).__name__}")


def safe_calc(expression: str):
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        return ast_calc(tree)
    except Exception:
        return None


def format_result(result) -> str:
    if result is None:
        return None
    if isinstance(result, float):
        if result == int(result):
            return str(int(result))
        return f"{result:.6g}"
    return str(result)


class Calculator(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        reply = await self.capability_worker.run_io_loop(
            "What would you like me to calculate?"
        )
        expr = words_to_expression(reply)
        result = safe_calc(expr)
        formatted = format_result(result)
        if formatted is None:
            await self.capability_worker.speak(
                "Sorry, I couldn't work that out. Try saying something like: "
                "fifteen plus twenty-seven, or square root of one hundred and forty-four."
            )
        else:
            await self.capability_worker.speak(f"The answer is {formatted}.")
        self.capability_worker.resume_normal_flow()
