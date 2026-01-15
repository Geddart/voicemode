"""
Client for the Audio Manager service.

Provides a simple interface for MCP tools to:
- Queue audio for playback
- Check service status
- Auto-start the service if not running
"""

import asyncio
import base64
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("audio_manager.client")

# Default configuration
DEFAULT_PORT = 8881
DEFAULT_TIMEOUT = 30.0
STARTUP_TIMEOUT = 10.0
HEALTH_CHECK_INTERVAL = 0.2


class AudioManagerClient:
    """
    Client for communicating with the Audio Manager service.

    Handles auto-starting the service if needed and provides
    a simple async interface for audio operations.
    """

    def __init__(
        self,
        port: Optional[int] = None,
        auto_start: bool = True,
    ):
        """
        Initialize the client.

        Args:
            port: Service port (default from env or 8881)
            auto_start: Whether to auto-start service if not running
        """
        self.port = port or int(os.getenv("VOICEMODE_AUDIO_MANAGER_PORT", str(DEFAULT_PORT)))
        self.auto_start = auto_start
        self.base_url = f"http://127.0.0.1:{self.port}"

    async def ensure_running(self) -> bool:
        """
        Ensure the Audio Manager service is running.

        Returns:
            True if service is running (or was started), False otherwise
        """
        if await self.health_check():
            return True

        if not self.auto_start:
            logger.warning("Audio Manager not running and auto_start is disabled")
            return False

        return await self._start_service()

    async def health_check(self, timeout: float = 1.0) -> bool:
        """
        Check if the service is healthy.

        Args:
            timeout: Request timeout in seconds

        Returns:
            True if service is healthy
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def _start_service(self) -> bool:
        """
        Start the Audio Manager service.

        Returns:
            True if service started successfully
        """
        logger.info("Starting Audio Manager service...")

        # Get the hotkey from environment
        hotkey = os.getenv("VOICEMODE_PAUSE_HOTKEY", "fn")

        # Start the service as a detached process
        try:
            # Use sys.executable to get the correct Python interpreter
            cmd = [
                sys.executable, "-m", "voice_mode.audio_manager",
                "--port", str(self.port),
                "--hotkey", hotkey,
            ]

            # Start detached from parent
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            logger.info(f"Started Audio Manager process (PID: {process.pid})")

        except Exception as e:
            logger.error(f"Failed to start Audio Manager: {e}")
            return False

        # Wait for service to be ready
        for _ in range(int(STARTUP_TIMEOUT / HEALTH_CHECK_INTERVAL)):
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            if await self.health_check():
                logger.info("Audio Manager service is ready")
                return True

        logger.error("Audio Manager failed to start within timeout")
        return False

    async def speak(
        self,
        audio_data: bytes,
        sample_rate: int = 24000,
        project: str = "unknown",
        priority: str = "normal",
    ) -> dict:
        """
        Queue audio for playback using reserve/fill for proper FIFO ordering.

        Args:
            audio_data: Raw audio bytes (16-bit signed integers)
            sample_rate: Sample rate in Hz
            project: Project/window name
            priority: Priority level (high, normal, low)

        Returns:
            Dict with queued status, position, item_id
        """
        if not await self.ensure_running():
            return {
                "queued": False,
                "error": "Audio Manager service not available",
            }

        try:
            # Use reserve/fill pattern for proper FIFO ordering
            reservation = await self.reserve(project=project, priority=priority)
            if not reservation.get("reserved"):
                return {
                    "queued": False,
                    "error": reservation.get("error", "Failed to reserve slot"),
                }

            item_id = reservation.get("item_id")
            position = reservation.get("position", 0)

            # Fill the reserved slot immediately (audio already available)
            fill_result = await self.fill(
                item_id=item_id,
                audio_data=audio_data,
                sample_rate=sample_rate,
            )

            if not fill_result.get("filled"):
                return {
                    "queued": False,
                    "error": fill_result.get("error", "Failed to fill slot"),
                }

            return {
                "queued": True,
                "item_id": item_id,
                "position": position,
            }
        except Exception as e:
            logger.error(f"Failed to queue audio: {e}")
            return {
                "queued": False,
                "error": str(e),
            }

    async def get_status(self) -> dict:
        """
        Get service status.

        Returns:
            Status dict or error dict
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/status")
                return response.json()
        except Exception as e:
            return {"error": str(e)}

    async def pause(self) -> bool:
        """Pause current playback."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.base_url}/pause")
                return response.json().get("paused", False)
        except Exception:
            return False

    async def resume(self) -> bool:
        """Resume paused playback."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.base_url}/resume")
                return not response.json().get("paused", True)
        except Exception:
            return False

    async def stop(self) -> bool:
        """Stop current playback."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.base_url}/stop")
                return response.json().get("stopped", False)
        except Exception:
            return False

    async def clear(self, project: Optional[str] = None) -> int:
        """
        Clear the queue.

        Args:
            project: Only clear items from this project (None = all)

        Returns:
            Number of items cleared
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                body = {"project": project} if project else {}
                response = await client.post(f"{self.base_url}/clear", json=body)
                return response.json().get("cleared", 0)
        except Exception:
            return 0

    async def wait_for_item(self, item_id: str, timeout: float = 120.0) -> bool:
        """
        Wait for a specific audio item to finish playing.

        Args:
            item_id: The item ID returned from speak()
            timeout: Maximum time to wait in seconds

        Returns:
            True if item completed, False if timeout or error
        """
        try:
            # Use a longer HTTP timeout than the wait timeout
            http_timeout = timeout + 5.0
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                response = await client.post(
                    f"{self.base_url}/wait/{item_id}",
                    params={"timeout": str(timeout)},
                )
                result = response.json()
                return result.get("completed", False)
        except Exception as e:
            logger.error(f"Failed to wait for item {item_id}: {e}")
            return False

    async def chime_allowed(self) -> bool:
        """
        Check if a chime is allowed (rate-limiting across all windows).

        This method both checks AND records the chime time if allowed.
        Call before playing a chime - if True is returned, the chime time
        is recorded and subsequent calls will return False until cooldown.

        Returns:
            True if chime is allowed, False if in cooldown
        """
        if not await self.ensure_running():
            # If service isn't running, allow chime (fail open)
            return True

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(f"{self.base_url}/chime-allowed")
                result = response.json()
                return result.get("allowed", True)
        except Exception as e:
            logger.warning(f"Failed to check chime permission: {e}")
            # Fail open - allow chime if we can't check
            return True

    async def reserve(
        self,
        project: str = "unknown",
        priority: str = "normal",
    ) -> dict:
        """
        Reserve a queue slot before generating audio.

        Call BEFORE starting TTS generation to ensure proper FIFO ordering
        across multiple concurrent requests from different windows.

        Args:
            project: Project/window name
            priority: Priority level (high, normal, low)

        Returns:
            Dict with reserved=True and item_id on success
        """
        if not await self.ensure_running():
            return {
                "reserved": False,
                "error": "Audio Manager service not available",
            }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.base_url}/reserve",
                    json={
                        "project": project,
                        "priority": priority,
                    },
                )
                return response.json()
        except Exception as e:
            logger.error(f"Failed to reserve slot: {e}")
            return {
                "reserved": False,
                "error": str(e),
            }

    async def fill(
        self,
        item_id: str,
        audio_data: bytes,
        sample_rate: int = 24000,
    ) -> dict:
        """
        Fill a reserved slot with audio data.

        Call after TTS generation completes with the item_id from reserve().

        Args:
            item_id: The item_id from reserve()
            audio_data: Raw audio bytes (16-bit signed integers)
            sample_rate: Sample rate in Hz

        Returns:
            Dict with filled=True on success
        """
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    f"{self.base_url}/fill/{item_id}",
                    json={
                        "audio_data": base64.b64encode(audio_data).decode(),
                        "sample_rate": sample_rate,
                    },
                )
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fill slot {item_id}: {e}")
            return {
                "filled": False,
                "error": str(e),
            }


# Convenience function for one-off usage
async def speak(
    audio_data: bytes,
    sample_rate: int = 24000,
    project: str = "unknown",
    priority: str = "normal",
) -> dict:
    """
    Convenience function to queue audio for playback.

    Creates a temporary client, ensures service is running, and queues audio.
    """
    client = AudioManagerClient()
    return await client.speak(audio_data, sample_rate, project, priority)
