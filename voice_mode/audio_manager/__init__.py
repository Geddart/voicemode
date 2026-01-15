"""
Audio Manager - Centralized HTTP audio service for VoiceMode.

This service handles:
- Audio queuing with priority support
- Audio playback coordination across multiple Claude Code windows
- Dictation pause via configurable hotkey (pauses audio when modifier key held)

The service runs on port 8881 by default and auto-starts when needed.
"""

__version__ = "0.1.0"

from .client import AudioManagerClient
from .queue import AudioQueue, QueueItem, Priority

__all__ = ["AudioManagerClient", "AudioQueue", "QueueItem", "Priority"]
