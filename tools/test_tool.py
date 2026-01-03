from tools.base import Tool
from core.tools import register_tool
import datetime

@register_tool
class TimeTool(Tool):
    name = "get_time"
    description = "Get the current date and time"

    async def run(self, params: str) -> str:
        now = datetime.datetime.now()
        return f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}"

@register_tool
class CalculatorTool(Tool):
    name = "calculate"
    description = "Do simple math. Params: math expression (e.g., 2+2, 15*3)"

    async def run(self, params: str) -> str:
        try:
            # Only allow safe math operations
            allowed = set('0123456789+-*/.() ')
            if not all(c in allowed for c in params):
                return "Error: Only numbers and +-*/() allowed"
            result = eval(params)
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {str(e)}"
