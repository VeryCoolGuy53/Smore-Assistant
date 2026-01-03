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

app = FastAPI(title=config.ASSISTANT_NAME)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Mount static files
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# Initialize Ollama client
ollama = OllamaClient()

# Store conversation history per session (simple in-memory for now)
conversations: dict[str, list] = {}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "assistant_name": config.ASSISTANT_NAME
    })

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    conversations[session_id] = []
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Add user message to history
            conversations[session_id].append({
                "role": "user",
                "content": data
            })
            
            # Build messages with system prompt
            messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
            messages.extend(conversations[session_id])
            
            # Stream response from Ollama
            full_response = ""
            async for chunk in ollama.chat(messages):
                full_response += chunk
                await websocket.send_text(chunk)
            
            # Send end marker
            await websocket.send_text("[END]")
            
            # Add assistant response to history
            conversations[session_id].append({
                "role": "assistant",
                "content": full_response
            })
            
    except WebSocketDisconnect:
        # Clean up conversation on disconnect
        if session_id in conversations:
            del conversations[session_id]

@app.get("/health")
async def health():
    return {"status": "ok", "assistant": config.ASSISTANT_NAME}
