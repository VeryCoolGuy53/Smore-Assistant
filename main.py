#!/usr/bin/env python3
"""
Smore Assistant - Personal AI Assistant
Run with: python main.py
"""
import os
import sys
import uvicorn
import config

# Force unbuffered output for real-time logging
os.environ['PYTHONUNBUFFERED'] = '1'
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

if __name__ == "__main__":
    print(f"Starting {config.ASSISTANT_NAME}...")
    print(f"Web UI: http://localhost:{config.PORT}")
    print(f"Using Ollama model: {config.OLLAMA_MODEL}")

    uvicorn.run(
        "web.app:app",
        host=config.HOST,
        port=config.PORT,
        reload=True  # Auto-reload on code changes during development
    )
