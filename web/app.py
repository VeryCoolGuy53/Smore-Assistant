import re
import bcrypt
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.sessions import SessionMiddleware
import sys
import os
import json
from datetime import datetime, timezone
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.ollama_client import OllamaClient
from core.memory import read_memory, update_memory, process_memory_update
from core.tools import parse_tool_call, strip_tool_call, execute_tool, get_tool_list, parse_thinking, strip_thinking, TOOLS

import tools  # This registers all tools

print(f"STARTUP: Registered tools: {list(TOOLS.keys())}")

app = FastAPI(title=config.ASSISTANT_NAME)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

ollama = OllamaClient()
conversations: dict[str, list] = {}
serializer = URLSafeTimedSerializer(config.SECRET_KEY)

def verify_password(password: str) -> bool:
    return bcrypt.checkpw(password.encode(), config.PASSWORD_HASH.encode())

def create_session_token() -> str:
    return serializer.dumps({"authenticated": True})

def verify_session_token(token: str) -> bool:
    try:
        data = serializer.loads(token, max_age=config.SESSION_EXPIRY)
        return data.get("authenticated", False)
    except (BadSignature, SignatureExpired):
        return False

def get_current_user(request: Request):
    token = request.session.get("auth_token")
    if not token or not verify_session_token(token):
        return None
    return True

def get_system_prompt() -> str:
    memory = read_memory()
    tool_list = get_tool_list()
    return config.SYSTEM_PROMPT.format(memory=memory, tools=tool_list)

def extract_text_before_tool(response: str) -> str:
    pattern = r"\[TOOL:[^\]]+\].*?\[/TOOL\]"
    match = re.search(pattern, response, re.DOTALL)
    if match:
        return response[:match.start()].strip()
    return response.strip()

def create_message(msg_type: str, **kwargs) -> str:
    """Create JSON message with timestamp."""
    data = {
        "type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs
    }
    return json.dumps(data)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if verify_password(password):
        request.session["auth_token"] = create_session_token()
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request, "assistant_name": config.ASSISTANT_NAME})

@app.get("/memory")
async def get_memory_endpoint(request: Request):
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"memory": read_memory()}

@app.get("/tools")
async def list_tools(request: Request):
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"tools": get_tool_list()}

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    # Check auth from session cookie
    session_cookie = websocket.cookies.get("session")
    if not session_cookie:
        await websocket.close(code=4001, reason="Not authenticated")
        return

    # Decode session to verify auth (must match SessionMiddleware's format)
    try:
        from itsdangerous import TimestampSigner, BadSignature
        import base64
        import json

        signer = TimestampSigner(str(config.SECRET_KEY))
        data = signer.unsign(session_cookie, max_age=config.SESSION_EXPIRY)
        session_data = json.loads(base64.b64decode(data))
        auth_token = session_data.get("auth_token")
        if not auth_token or not verify_session_token(auth_token):
            await websocket.close(code=4001, reason="Not authenticated")
            return
    except (BadSignature, Exception) as e:
        print(f"Auth error: {e}")
        await websocket.close(code=4001, reason="Not authenticated")
        return

    session_id = str(id(websocket))
    conversations[session_id] = []

    try:
        while True:
            data = await websocket.receive_text()
            print(f"USER: {data}")
            sys.stdout.flush()
            conversations[session_id].append({"role": "user", "content": data})

            # Echo user message to frontend with timestamp
            await websocket.send_text(create_message("user_message", content=data))

            messages = [{"role": "system", "content": get_system_prompt()}]
            messages.extend(conversations[session_id])

            # Inject initial thinking prompt
            messages.append({
                "role": "user",
                "content": "Before using tools, think through your strategy: Review what you already know from our conversation. What information have you already gathered? What's still missing? Use what you know to be efficient - don't re-search things you've already found. Output your plan in [THINKING]...[/THINKING] tags."
            })

            max_iterations = 20
            iteration = 0
            full_conversation_response = ""

            while iteration < max_iterations:
                iteration += 1
                print(f"DEBUG: Iteration {iteration}")

                # Inject reflection prompt every 3 iterations
                if iteration > 1 and iteration % 3 == 0:
                    messages.append({
                        "role": "user",
                        "content": "Progress check: Are you making progress? If yes, continue carefully. If no, try ONE different approach (different keywords, broader search, different account). Don't launch many tools at once - be strategic and measured."
                    })
                    print(f"DEBUG: Injected reflection prompt at iteration {iteration}")

                # Send thinking indicator if not first iteration
                if iteration > 1:
                    await websocket.send_text(create_message("thinking", iteration=iteration))

                # Stream directly from Ollama - filter out thinking and tool calls before sending to frontend
                response_buffer = ""
                in_thinking = False
                in_tool = False

                async for chunk in ollama.chat(messages, stream=True):
                    # Accumulate for tool detection
                    response_buffer += chunk

                    # Filter out thinking and tool content from streaming display
                    filtered_chunk = ""
                    for char in chunk:
                        # Detect start of thinking block
                        if char == '[' and response_buffer.endswith('[THINKING'):
                            in_thinking = True

                        # Detect start of tool block
                        if char == '[' and response_buffer[-6:].startswith('[TOOL:'):
                            in_tool = True

                        # Only add char if not in thinking or tool block
                        if not in_thinking and not in_tool:
                            filtered_chunk += char

                        # Detect end of thinking block
                        if char == ']' and response_buffer.endswith('[/THINKING]'):
                            in_thinking = False

                        # Detect end of tool block
                        if char == ']' and response_buffer.endswith('[/TOOL]'):
                            in_tool = False

                    # Only send non-thinking, non-tool content to frontend
                    if filtered_chunk:
                        await websocket.send_text(create_message("assistant_chunk", content=filtered_chunk))

                # Process memory updates on complete response
                response = process_memory_update(response_buffer)
                print(f"DEBUG: AI response: {response[:200]}...")

                # Parse and log thinking (internal reasoning, not shown to user)
                thinking = parse_thinking(response)
                if thinking:
                    print(f"THINKING: {thinking}")
                    sys.stdout.flush()
                    # Strip thinking from response before processing tools
                    response = strip_thinking(response)

                tool_call = parse_tool_call(response)
                print(f"DEBUG: Tool call parsed: {tool_call}")

                if tool_call:
                    tool_name, params = tool_call
                    print(f"DEBUG: Executing {tool_name} with params: {params}")

                    text_before = extract_text_before_tool(response)
                    if text_before:
                        # Text already streamed to frontend - just track it
                        full_conversation_response += text_before

                    # Send tool start
                    start_time = time.time()
                    await websocket.send_text(create_message(
                        "tool_start",
                        tool_name=tool_name,
                        params=params,
                        iteration=iteration
                    ))

                    # Execute tool
                    try:
                        tool_result = await execute_tool(tool_name, params, depth=0, websocket=websocket)
                        print(f"DEBUG: Tool result: {tool_result}")
                    except Exception as e:
                        tool_result = f"Error: {str(e)}"
                        print(f"DEBUG: Tool error: {e}")

                    # Send tool result (NEW - visible to user)
                    duration_ms = int((time.time() - start_time) * 1000)
                    await websocket.send_text(create_message(
                        "tool_result",
                        tool_name=tool_name,
                        result=tool_result,
                        iteration=iteration,
                        duration_ms=duration_ms
                    ))

                    # Update conversation
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": f"[Tool Result from {tool_name}]: {tool_result}"
                    })
                else:
                    # Final response already streamed to frontend - just track it
                    cleaned = strip_tool_call(response)
                    if cleaned:
                        print(f"ASSISTANT: {cleaned}")
                        sys.stdout.flush()
                        # Text already streamed to frontend - just track it
                        full_conversation_response += cleaned
                        break
                    else:
                        # Model generated only thinking, no response - continue to next iteration
                        print(f"DEBUG: Model generated only thinking, continuing...")
                        if iteration >= max_iterations - 1:
                            # Hit max iterations without response, send error
                            error_msg = "I apologize, I'm having trouble formulating a response. Could you rephrase your request?"
                            for char in error_msg:
                                await websocket.send_text(create_message("assistant_chunk", content=char))
                            full_conversation_response += error_msg
                            break
                        continue

            # Send end message
            await websocket.send_text(create_message("end", total_iterations=iteration))

            if full_conversation_response.strip():
                conversations[session_id].append({
                    "role": "assistant",
                    "content": full_conversation_response.strip()
                })

    except WebSocketDisconnect:
        if session_id in conversations:
            del conversations[session_id]
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

@app.get("/health")
async def health():
    return {"status": "ok", "assistant": config.ASSISTANT_NAME}
