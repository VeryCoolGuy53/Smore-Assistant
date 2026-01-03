from abc import ABC, abstractmethod
from typing import Optional

class Tool(ABC):
    """Base class for all tools the assistant can use."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, params: str) -> str:
        """
        Execute the tool with given parameters.

        Args:
            params: Raw parameter string from AI

        Returns:
            Short summary of results (keep it concise to save context!)
        """
        pass

    def get_help(self) -> str:
        """Return help text for this tool."""
        return f"{self.name}: {self.description}"
