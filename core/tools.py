import re
from typing import Optional, Tuple

# Tool registry - tools register themselves here
TOOLS: dict = {}

def register_tool(tool):
    """Register a tool in the global registry."""
    TOOLS[tool.name] = tool
    return tool

def get_tool_list() -> str:
    """Get formatted list of available tools for the system prompt."""
    if not TOOLS:
        return "No tools available."

    lines = []
    for name, tool in TOOLS.items():
        lines.append(f"- {name}: {tool.description}")
    return "\n".join(lines)

def parse_tool_call(response: str) -> Optional[Tuple[str, str]]:
    """
    Extract tool call from response.
    Returns (tool_name, params) or None if no tool call found.
    """
    pattern = r"\[TOOL:([^\]]+)\](.*?)\[/TOOL\]"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        tool_name = match.group(1).strip()
        params = match.group(2).strip()
        return (tool_name, params)

    return None

def strip_tool_call(response: str) -> str:
    """Remove tool call block from response."""
    pattern = r"\[TOOL:[^\]]+\].*?\[/TOOL\]"
    return re.sub(pattern, "", response, flags=re.DOTALL).strip()

async def execute_tool(name: str, params: str) -> str:
    """Execute a tool by name with given params."""
    if name not in TOOLS:
        return f"Error: Unknown tool. Available: {', '.join(TOOLS.keys())}"

    try:
        result = await TOOLS[name].run(params)
        return result
    except Exception as e:
        return f"Error running {name}: {str(e)}"
