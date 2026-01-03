import re
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.ollama_client import OllamaClient
from core.memory import read_memory, update_memory
from core.tools import parse_tool_call, strip_tool_call, execute_tool, get_tool_list

# Import tools to register them
import tools.test_tool  # This will auto-register the test tool

app = FastAPI(title=config.ASSISTANT_NAME)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Mount static files
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# Initialize Ollama client
ollama = OllamaClient()

# Store conversation history per session
conversations: dict[str, list] = {}

def get_system_prompt() -> str:
    """Get system prompt with current memory and tools injected."""
    memory = read_memory()
    tool_list = get_tool_list()
    return config.SYSTEM_PROMPT.format(memory=memory, tools=tool_list)

def process_memory_update(response: str) -> str:
    """Extract and apply memory updates, return cleaned response."""
    pattern = r'\[MEMORY_UPDATE\](.*?)\[/MEMORY_UPDATE\]'
    match = re.search(pattern, response, re.DOTALL)

    if match:
        new_memory = match.group(1).strip()
        if len(new_memory) <= 2000:
            update_memory(new_memory)
            print(f"Memory updated: {len(new_memory)} chars")
        response = re.sub(pattern, '', response, flags=re.DOTALL).strip()

    return response

async def get_full_response(messages: list) -> str:
    """Get complete (non-streaming) response from Ollama."""
    full_response = ""
    async for chunk in ollama.chat(messages, stream=True):
        full_response += chunk
    return full_response

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "assistant_name": config.ASSISTANT_NAME
    })

@app.get("/memory")
async def get_memory():
    return {"memory": read_memory()}

@app.get("/tools")
async def list_tools():
    return {"tools": get_tool_list()}

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    conversations[session_id] = []

    try:
        while True:
            data = await websocket.receive_text()

            conversations[session_id].append({
                "role": "user",
                "content": data
            })

            # Build messages with system prompt
            messages = [{"role": "system", "content": get_system_prompt()}]
            messages.extend(conversations[session_id])

            # Get initial response
            full_response = await get_full_response(messages)

            # Tool execution loop - keep running tools until no more tool calls
            max_tool_calls = 5  # Prevent infinite loops
            tool_calls = 0

            while parse_tool_call(full_response) and tool_calls < max_tool_calls:
                tool_calls += 1
                tool_name, params = parse_tool_call(full_response)
                print(f"Executing tool: {tool_name} with params: {params}")

                # Execute the tool
                tool_result = await execute_tool(tool_name, params)
                print(f"Tool result: {tool_result}")

                # Send tool status to user (so they know something is happening)
                await websocket.send_text(f"[Using {tool_name}...]\n")

                # Add tool result as system message (temporary, not in history)
                messages.append({
                    "role": "system",
                    "content": f"Tool '{tool_name}' returned: {tool_result}"
                })

                # Get new response with tool result
                full_response = await get_full_response(messages)

                # Remove the temporary tool result message
                messages.pop()

            # Process memory updates and clean response
            cleaned_response = process_memory_update(full_response)
            cleaned_response = strip_tool_call(cleaned_response)

            # Send final response to user
            await websocket.send_text(cleaned_response)
            await websocket.send_text("[END]")

            # Store cleaned response in history
            conversations[session_id].append({
                "role": "assistant",
                "content": cleaned_response
            })

    except WebSocketDisconnect:
        if session_id in conversations:
            del conversations[session_id]

@app.get("/health")
async def health():
    return {"status": "ok", "assistant": config.ASSISTANT_NAME}
