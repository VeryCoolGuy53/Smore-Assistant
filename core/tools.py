import re
from typing import Optional, Tuple

# Tool registry - tools register themselves here
TOOLS: dict = {}

def register_tool(tool):
    """Register a tool in the global registry."""
    TOOLS[tool.name] = tool()
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
    # Try exact pattern first
    pattern = r"\[TOOL:([^\]]+)\](.*?)\[/TOOL\]"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        tool_name = match.group(1).strip()
        params = match.group(2).strip()
        return (tool_name, params)

    # Fallback: lenient pattern for malformed closing tags like [/TOO], [/TOOL, etc.
    lenient_pattern = r"\[TOOL:([^\]]+)\](.*?)\[/TOO[L]?\]?"
    match = re.search(lenient_pattern, response, re.DOTALL)

    if match:
        tool_name = match.group(1).strip()
        params = match.group(2).strip()
        return (tool_name, params)

    return None

def strip_tool_call(response: str) -> str:
    """Remove tool call block from response."""
    # Try exact pattern first
    pattern = r"\[TOOL:[^\]]+\].*?\[/TOOL\]"
    result = re.sub(pattern, "", response, flags=re.DOTALL).strip()

    if result != response.strip():
        return result

    # Fallback for malformed closing tags
    lenient_pattern = r"\[TOOL:[^\]]+\].*?\[/TOO[L]?\]?"
    return re.sub(lenient_pattern, "", response, flags=re.DOTALL).strip()

def parse_thinking(response: str) -> Optional[str]:
    """
    Extract thinking content from response.
    Returns thinking content or None if no thinking tags found.
    """
    pattern = r"\[THINKING\](.*?)\[/THINKING\]"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        return match.group(1).strip()

    return None

def strip_thinking(response: str) -> str:
    """Remove thinking tags from response."""
    pattern = r"\[THINKING\].*?\[/THINKING\]"
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
