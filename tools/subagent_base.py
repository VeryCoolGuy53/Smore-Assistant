from abc import abstractmethod
from tools.base import Tool
from core.ollama_client import OllamaClient
from core.tools import execute_tool, parse_tool_call, get_tool_list_filtered
from core.memory import process_memory_update
import config

class SubagentTool(Tool):
    """Base class for all subagent tools."""

    # Override in subclasses
    name: str = ""
    description: str = ""
    system_prompt_template: str = ""  # Can include {tools} placeholder
    max_iterations: int = config.SUBAGENT_MAX_ITERATIONS

    def __init__(self):
        self.ollama = OllamaClient(
            base_url=config.OLLAMA_BASE_URL,
            model=config.OLLAMA_MODEL
        )

    async def run(self, params: str) -> str:
        """Execute subagent with task delegation."""
        from core.tools import _current_depth

        depth = _current_depth + 1

        # Check max depth
        if depth > config.SUBAGENT_MAX_DEPTH:
            return "Error: Maximum subagent nesting depth exceeded"

        # Initialize conversation
        system_prompt = self._build_system_prompt(depth)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": params}
        ]

        # Tool execution loop (similar to web/app.py:162-203)
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1

            # Get AI response
            full_response = await self._get_full_response(messages)

            # Process memory updates
            full_response = process_memory_update(full_response)

            # Check for tool call
            tool_call = parse_tool_call(full_response)

            if not tool_call:
                # No tool call - return final response
                return full_response

            tool_name, tool_params = tool_call

            # Send subagent tool start to UI if websocket available
            from core import tools
            import time
            import json
            websocket = tools._current_websocket

            if websocket:
                try:
                    msg = json.dumps({
                        "type": "subagent_tool_start",
                        "tool_name": tool_name,
                        "params": tool_params,
                        "subagent": self.name,
                        "iteration": iteration
                    })
                    await websocket.send_text(msg)
                except:
                    pass  # Don't fail if websocket send fails

            # Execute tool at increased depth
            old_depth = tools._current_depth
            tools._current_depth = depth
            start_time = time.time()
            try:
                tool_result = await execute_tool(tool_name, tool_params, depth)
            finally:
                tools._current_depth = old_depth

            # Send subagent tool end to UI
            if websocket:
                try:
                    elapsed = time.time() - start_time
                    msg = json.dumps({
                        "type": "subagent_tool_end",
                        "tool_name": tool_name,
                        "result": tool_result[:200] + ("..." if len(tool_result) > 200 else ""),
                        "duration": round(elapsed, 2)
                    })
                    await websocket.send_text(msg)
                except:
                    pass

            # Append to conversation
            messages.append({"role": "assistant", "content": full_response})
            messages.append({"role": "user", "content": f"[Tool Result from {tool_name}]: {tool_result}"})

        # Max iterations reached
        return f"Subagent reached max iterations ({self.max_iterations}). Last response: {full_response[:200]}..."

    def _build_system_prompt(self, depth: int) -> str:
        """Build system prompt with tools (NO memory for lean context)."""
        tools = get_tool_list_filtered(depth)

        depth_notice = ""
        if depth >= config.SUBAGENT_MAX_DEPTH:
            depth_notice = "\n\nIMPORTANT: You are at maximum nesting depth. You cannot delegate to other subagents."

        return self.system_prompt_template.format(tools=tools) + depth_notice

    async def _get_full_response(self, messages: list) -> str:
        """Get complete response from Ollama."""
        chunks = []
        async for chunk in self.ollama.chat(messages):
            chunks.append(chunk)
        return "".join(chunks)
