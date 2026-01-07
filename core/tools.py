import re
from typing import Optional, Tuple

# Tool registry - tools register themselves here
TOOLS: dict = {}

# Track current recursion depth for subagents
_current_depth = 0

# Track current websocket for subagent UI updates (set by web/app.py)
_current_websocket = None

def register_tool(tool):
    """Register a tool in the global registry."""
    TOOLS[tool.name] = tool()
    return tool

def get_tool_list() -> str:
    """Get formatted list of available tools for the system prompt."""
    return get_tool_list_filtered(depth=0)

def get_tool_list_filtered(depth: int = 0) -> str:
    """Get formatted list of available tools, filtered by recursion depth."""
    if not TOOLS:
        return "No tools available."

    # Import config here to avoid circular imports
    import config

    lines = []
    for name, tool in TOOLS.items():
        # If at max depth - 1, exclude subagent tools to prevent further nesting
        if depth >= config.SUBAGENT_MAX_DEPTH - 1:
            # Check if tool is a subagent by checking if it has the SubagentTool base class
            from tools.base import Tool
            tool_class = tool.__class__
            # Check if any parent class name contains "Subagent"
            is_subagent = any("Subagent" in base.__name__ for base in tool_class.__mro__)
            if is_subagent:
                continue

        lines.append(f"- {name}: {tool.description}")

    return "\n".join(lines) if lines else "No tools available."

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

async def execute_tool(name: str, params: str, depth: int = 0, websocket=None) -> str:
    """Execute a tool by name with given params at specified depth."""
    global _current_depth, _current_websocket

    if name not in TOOLS:
        return f"Error: Unknown tool. Available: {', '.join(TOOLS.keys())}"

    # Import config here to avoid circular imports
    import config

    # Check depth limits
    if depth > config.SUBAGENT_MAX_DEPTH:
        return "Error: Maximum subagent nesting depth exceeded"

    # Set current depth and websocket for subagents to access
    old_depth = _current_depth
    old_websocket = _current_websocket
    _current_depth = depth
    if websocket is not None:
        _current_websocket = websocket

    try:
        result = await TOOLS[name].run(params)
        return result
    except Exception as e:
        return f"Error running {name}: {str(e)}"
    finally:
        _current_depth = old_depth
        _current_websocket = old_websocket
