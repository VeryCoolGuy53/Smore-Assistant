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
    """Get system prompt with current memory injected."""
    memory = read_memory()
    return config.SYSTEM_PROMPT.format(memory=memory)

def process_memory_update(response: str) -> str:
    """Extract and apply memory updates, return cleaned response."""
    pattern = r'\[MEMORY_UPDATE\](.*?)\[/MEMORY_UPDATE\]'
    match = re.search(pattern, response, re.DOTALL)
    
    if match:
        new_memory = match.group(1).strip()
        if len(new_memory) <= 2000:
            update_memory(new_memory)
            print(f"Memory updated: {len(new_memory)} chars")
        # Remove the memory block from response
        response = re.sub(pattern, '', response, flags=re.DOTALL).strip()
    
    return response

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "assistant_name": config.ASSISTANT_NAME
    })

@app.get("/memory")
async def get_memory():
    """View current memory (for debugging)."""
    return {"memory": read_memory()}

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
            
            # Build messages with current memory in system prompt
            messages = [{"role": "system", "content": get_system_prompt()}]
            messages.extend(conversations[session_id])
            
            # Stream response
            full_response = ""
            async for chunk in ollama.chat(messages):
                full_response += chunk
            
            # Process any memory updates and clean response
            cleaned_response = process_memory_update(full_response)
            
            # Send cleaned response to user
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
