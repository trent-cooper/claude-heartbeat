"""Abstract base class for messaging channels."""

from abc import ABC, abstractmethod


class Channel(ABC):
    """Base class for message delivery channels."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def send(self, message: str) -> tuple[bool, str]:
        """Send a message. Returns (success, detail_message)."""
        ...

    @abstractmethod
    def validate_config(self) -> tuple[bool, str]:
        """Validate that channel config is complete. Returns (valid, error_message)."""
        ...
