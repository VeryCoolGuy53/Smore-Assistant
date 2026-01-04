# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Personal AI assistant application using Ollama LLM with a FastAPI web interface. Features include tool-based extensibility, Gmail integration via OAuth, persistent memory, and session-based authentication.

## Development Commands

### Running the Application
```bash
# Start the server (auto-reload enabled)
python main.py

# Server runs on http://localhost:8888
# Uses Ollama model: qwen3-coder:30b-a3b-q4_K_M at http://localhost:11434
```

### Gmail Authorization
```bash
# Authorize a Gmail account (creates token in tokens/ directory)
python auth_gmail.py

# Follow prompts to authorize via OAuth flow
# Multiple accounts can be authorized - tokens stored as tokens/{email}.json
```

### Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables (copy .env.example to .env)
# Required: SECRET_KEY, PASSWORD_HASH for authentication
```

## Architecture

### Core Components

**Web Layer** ([web/app.py](web/app.py))
- FastAPI application with WebSocket-based chat interface
- Session-based authentication using bcrypt + itsdangerous
- Templates: index.html (chat UI), login.html (auth)
- WebSocket endpoint `/ws/chat` handles streaming responses and tool execution loop

**LLM Client** ([core/ollama_client.py](core/ollama_client.py))
- Async HTTP client for Ollama API
- Streaming chat responses via `AsyncGenerator`
- Configurable base URL and model via [config.py](config.py)

**Tool System** ([core/tools.py](core/tools.py))
- Global `TOOLS` registry for all available tools
- `@register_tool` decorator auto-registers tool classes
- Tool call format: `[TOOL:tool_name]parameters[/TOOL]`
- Tools return concise string results to conserve context

**Memory System** ([core/memory.py](core/memory.py))
- Persistent memory stored in [memory.md](memory.md)
- 2KB size limit to prevent bloat
- Memory injected into system prompt on every request
- AI can update memory via `[MEMORY_UPDATE]content[/MEMORY_UPDATE]` tags

### Tool Execution Flow

1. User sends message via WebSocket
2. Message added to conversation history with system prompt
3. Assistant responds (streaming to UI)
4. If response contains `[TOOL:name]params[/TOOL]`:
   - Extract and execute tool
   - Append tool result to conversation as system message
   - Continue loop (max 10 iterations to prevent infinite loops)
5. Final response streamed to user, saved to conversation history

### Creating New Tools

Tools inherit from [tools/base.py](tools/base.py) `Tool` class:

```python
from tools.base import Tool
from core.tools import register_tool

@register_tool
class MyTool(Tool):
    name = "my_tool"
    description = "Brief description for AI system prompt"

    async def run(self, params: str) -> str:
        # params = raw string from [TOOL:my_tool]params[/TOOL]
        # Return concise result string (saves context!)
        return "Tool result"
```

Tools auto-register on import. Import in [tools/\_\_init\_\_.py](tools/__init__.py) to activate.

**IMPORTANT: Design tools to accept multiple parameter formats**

The AI may send parameters in various formats depending on context. Tools should be flexible:

```python
# Example: Email search tool accepting both formats
# Format 1: "email@domain query"
# Format 2: "email@domain:query"

async def run(self, params: str) -> str:
    # Parse flexibly - support both space and colon separators
    account = None
    query = params

    first_word = params.split(None, 1)[0] if params else ""

    # Space-separated format
    if "@" in first_word and ":" not in first_word:
        parts = params.split(None, 1)
        if len(parts) == 2:
            account = parts[0]
            query = parts[1]

    # Colon-separated format
    elif ":" in params and "@" in params:
        colon_pos = params.index(":")
        at_pos = params.index("@")
        if at_pos < colon_pos:
            account, query = params.split(":", 1)

    # Use account and query...
```

Why this matters: The AI doesn't have rigid output formatting. Being flexible prevents bugs where valid tool calls fail due to minor format differences.

### Gmail Integration

**OAuth Flow** ([auth_gmail.py](auth_gmail.py))
- Manual OAuth2 flow with redirect URI `http://localhost:8889/`
- Tokens saved to `tokens/{email}.json`
- Scopes: `gmail.readonly`, `gmail.compose`

**Email Tools** ([tools/email_tool.py](tools/email_tool.py))
- `list_email_accounts`: List authorized accounts
- `search_emails`: Search with Gmail query syntax (`from:`, `subject:`, etc.)
- `read_email`: Read full email content (truncated to 500 chars)
- `create_draft`: Create email draft in Gmail

Tool parameters support optional account prefix: `account@example.com:query`

### Configuration

**[config.py](config.py)**
- Ollama settings (base URL, model)
- Web server (host, port)
- Authentication (SECRET_KEY, PASSWORD_HASH, session expiry)
- System prompt template with `{tools}` and `{memory}` placeholders

**Environment Variables** ([.env](/.env))
- `SECRET_KEY`: Session signing key
- `PASSWORD_HASH`: bcrypt hash of login password

### Key Design Patterns

**Tool Call Parsing**: Regex-based with fallback for malformed tags ([core/tools.py:22-45](core/tools.py#L22-L45))

**Streaming Architecture**: FastAPI WebSocket + Ollama streaming API enables real-time UI updates

**Security**: Session tokens expire after 24 hours, credentials never committed (see [.gitignore](.gitignore))

**Context Management**:
- Conversations stored per WebSocket session ID
- System prompt regenerated each iteration to include latest memory and tool list
- Tool results injected as user messages to maintain conversation flow

## Important Notes

- Ollama must be running locally on port 11434
- Gmail requires `credentials.json` from Google Cloud Console (OAuth 2.0 Client)
- Password must be hashed with bcrypt and set in `.env` as `PASSWORD_HASH`
- Tools should return brief summaries to avoid context bloat
- Maximum 10 tool iterations per message to prevent loops
