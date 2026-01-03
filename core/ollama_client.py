import httpx
from typing import AsyncGenerator
import config

class OllamaClient:
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or config.OLLAMA_BASE_URL
        self.model = model or config.OLLAMA_MODEL
        
    async def chat(self, messages: list[dict], stream: bool = True) -> AsyncGenerator[str, None]:
        """Send a chat request to Ollama and stream the response."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": stream
            }
            
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            import json
                            data = json.loads(line)
                            if "message" in data and "content" in data["message"]:
                                yield data["message"]["content"]
            else:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                yield data["message"]["content"]
    
    async def chat_simple(self, user_message: str, system_prompt: str = None) -> AsyncGenerator[str, None]:
        """Simple chat with just a user message."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        
        async for chunk in self.chat(messages):
            yield chunk
