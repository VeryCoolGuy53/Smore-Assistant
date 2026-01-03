# Ollama settings
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:12b"  # or qwen3-coder:30b-a3b-q4_K_M for coding tasks

# Web server settings
HOST = "0.0.0.0"
PORT = 8888

# Assistant settings
ASSISTANT_NAME = "Smore Assistant"
SYSTEM_PROMPT = """You are a helpful personal assistant. You can help with tasks, answer questions, and control various services.
Be concise and helpful. If you don't know something, say so."""
