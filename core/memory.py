import os
import re
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "memory.md"

def read_memory() -> str:
    """Read the current memory file."""
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text()
    return ""

def update_memory(new_content: str) -> bool:
    """Replace memory file with new content. Keep it small!"""
    # Limit size to prevent bloat (max ~2KB)
    if len(new_content) > 2000:
        return False
    MEMORY_FILE.write_text(new_content)
    return True

def append_to_section(section: str, note: str) -> bool:
    """Add a note to a specific section. Keeps things organized."""
    content = read_memory()

    # Find the section and append
    section_header = f"## {section}"
    if section_header in content:
        lines = content.split("\n")
        new_lines = []
        found_section = False
        added = False

        for i, line in enumerate(lines):
            new_lines.append(line)
            if line.strip() == section_header:
                found_section = True
            elif found_section and not added:
                # Add after first line of section (which is usually a placeholder)
                if line.startswith("- ") or line.startswith("##") or line == "":
                    new_lines.insert(-1, f"- {note}")
                    added = True
                    found_section = False

        if added:
            return update_memory("\n".join(new_lines))

    return False

def process_memory_update(response: str) -> str:
    """Process and extract memory updates from AI response."""
    pattern = r"\[MEMORY_UPDATE\](.*?)\[/MEMORY_UPDATE\]"
    match = re.search(pattern, response, re.DOTALL)
    if match:
        new_content = match.group(1).strip()
        update_memory(new_content)
        # Remove the memory update tag from response
        return re.sub(pattern, "", response, flags=re.DOTALL).strip()
    return response
