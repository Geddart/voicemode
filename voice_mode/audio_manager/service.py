"""
Main Audio Manager service.

Coordinates:
- Audio queue management
- Audio playback
- Hotkey monitoring for dictation pause
- HTTP API server
"""

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn

from .queue import AudioQueue, Priority
from .player import AudioPlaybackManager
from .hotkey import HotkeyMonitor
from .api import create_app, set_service

logger = logging.getLogger("audio_manager.service")

# PID file for service management
PID_FILE = Path.home() / ".voicemode" / "audio_manager.pid"


class AudioManagerService:
    """
    Centralized audio manager service.

    Handles audio queuing, playback, and hotkey-based pause/resume.
    Runs an HTTP server for external control.
    """

    def __init__(self, port: int = 8881, hotkey: str = "fn"):
        """
        Initialize the audio manager service.

        Args:
            port: HTTP server port
            hotkey: Modifier key for pause (fn, ctrl, option, command, shift)
        """
        self.port = port
        self.hotkey_name = hotkey

        # Core components
        self.queue = AudioQueue()
        self.player = AudioPlaybackManager()
        self.hotkey_monitor = HotkeyMonitor(
            hotkey=hotkey,
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
        )

        # State
        self._running = False
        self._playback_task: Optional[asyncio.Task] = None
        self._dictation_active = False

        # Item completion tracking for blocking wait support
        self._item_events: dict[str, asyncio.Event] = {}
        self._events_lock = threading.Lock()

        # Chime rate-limiting (shared across all windows)
        self._last_chime_time: float = 0.0
        self._chime_cooldown: float = 60.0  # seconds

        # Set up API
        set_service(self)

    def _on_hotkey_press(self):
        """Called when the pause hotkey is pressed."""
        logger.info(f"Dictation started (hotkey: {self.hotkey_name})")
        self._dictation_active = True
        self.player.pause()

    def _on_hotkey_release(self):
        """Called when the pause hotkey is released."""
        logger.info(f"Dictation ended (hotkey: {self.hotkey_name})")
        self._dictation_active = False
        self.player.resume()

    def queue_audio(
        self,
        audio_data: bytes,
        sample_rate: int,
        project: str = "unknown",
        priority: Priority = Priority.NORMAL,
    ) -> dict:
        """Queue audio for playback."""
        result = self.queue.enqueue(
            audio_data=audio_data,
            sample_rate=sample_rate,
            project=project,
            priority=priority,
        )

        # Create event immediately when queued (before /wait can be called)
        # This prevents race condition where /wait is called before event exists
        with self._events_lock:
            self._item_events[result["item_id"]] = asyncio.Event()

        return result

    def pause(self) -> bool:
        """Pause current playback."""
        return self.player.pause()

    def resume(self) -> bool:
        """Resume paused playback."""
        return self.player.resume()

    def stop(self) -> bool:
        """Stop current playback."""
        return self.player.stop()

    def clear_queue(self, project: Optional[str] = None) -> int:
        """Clear items from the queue."""
        return self.queue.clear(project)

    def reserve_slot(
        self,
        project: str = "unknown",
        priority: Priority = Priority.NORMAL,
    ) -> dict:
        """
        Reserve a queue slot before generating audio.

        Call BEFORE starting TTS generation for proper FIFO ordering.

        Returns:
            Dict with reserved=True, item_id, and should_announce
        """
        result = self.queue.reserve(project=project, priority=priority)

        # Create event immediately for wait support
        with self._events_lock:
            self._item_events[result["item_id"]] = asyncio.Event()

        # Determine if announcement is needed (different project ahead/playing)
        should_announce = False

        # Check if audio from different project is currently playing
        current_project = self.player.current_project
        logger.debug(f"should_announce check: project={project}, current_project={current_project}")
        if current_project and current_project != project:
            should_announce = True
            logger.info(f"should_announce=True: different project playing ({current_project} != {project})")

        # Check if audio from different project is ahead in queue
        if not should_announce:
            with self.queue._lock:
                queue_projects = [item.project for item in self.queue._items]
                logger.debug(f"Queue projects: {queue_projects}")
                for item in self.queue._items:
                    if item.item_id == result["item_id"]:
                        break  # Stop at our own item
                    if item.project != project:
                        should_announce = True
                        logger.info(f"should_announce=True: different project in queue ({item.project} != {project})")
                        break

        result["should_announce"] = should_announce
        logger.debug(f"Final should_announce={should_announce} for project={project}")
        return result

    def fill_slot(
        self,
        item_id: str,
        audio_data: bytes,
        sample_rate: int = 24000,
    ) -> dict:
        """
        Fill a reserved slot with audio data.

        Call after TTS generation completes.

        Returns:
            Dict with filled=True on success
        """
        return self.queue.fill(
            item_id=item_id,
            audio_data=audio_data,
            sample_rate=sample_rate,
        )

    def check_chime_allowed(self) -> dict:
        """
        Check if a chime is allowed (rate-limiting).

        Returns dict with:
            allowed: True if chime can play
            seconds_remaining: Time until next chime allowed (0 if allowed)
        """
        now = time.time()
        elapsed = now - self._last_chime_time
        if elapsed >= self._chime_cooldown:
            # Chime allowed - record the time
            self._last_chime_time = now
            return {"allowed": True, "seconds_remaining": 0}
        else:
            remaining = self._chime_cooldown - elapsed
            return {"allowed": False, "seconds_remaining": round(remaining, 1)}

    def get_status(self) -> dict:
        """Get comprehensive service status."""
        queue_status = self.queue.get_status()
        player_status = self.player.get_status()
        hotkey_status = self.hotkey_monitor.get_status()

        return {
            **player_status,
            **queue_status,
            "dictation_active": self._dictation_active,
            "hotkey": hotkey_status["hotkey"],
            "hotkey_pressed": hotkey_status["is_pressed"],
        }

    async def wait_for_item(self, item_id: str, timeout: float = 120.0) -> bool:
        """
        Wait for a specific audio item to finish playing.

        Args:
            item_id: The item ID returned from queue_audio()
            timeout: Maximum time to wait in seconds

        Returns:
            True if item completed, False if timeout
        """
        with self._events_lock:
            event = self._item_events.get(item_id)

        if event is None:
            # Item already completed and cleaned up, or never existed
            # In either case, treat as completed
            return True

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for item {item_id}")
            return False

    async def _cleanup_item_event(self, item_id: str, delay: float = 60.0):
        """Clean up event after delay to prevent memory leak."""
        await asyncio.sleep(delay)
        with self._events_lock:
            self._item_events.pop(item_id, None)

    async def _playback_loop(self):
        """
        Main playback loop.

        Continuously dequeues and plays audio items.
        """
        logger.info("Playback loop started")

        while self._running:
            # Check for next item
            item = self.queue.dequeue()

            if item is None:
                # No items, wait a bit
                await asyncio.sleep(0.1)
                continue

            logger.info(f"Playing audio from {item.project} (priority: {item.priority.name})")

            # Play in thread pool to not block async loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.player.play,
                item.audio_data,
                item.sample_rate,
                item.project,
            )

            # Signal completion for any waiters
            with self._events_lock:
                event = self._item_events.get(item.item_id)
                if event:
                    event.set()

            # Schedule cleanup after 60s to prevent memory leak
            asyncio.create_task(self._cleanup_item_event(item.item_id, delay=60.0))

        logger.info("Playback loop stopped")

    async def run(self):
        """Run the audio manager service."""
        self._running = True

        # Write PID file
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        logger.info(f"PID file written: {PID_FILE}")

        # Set up signal handlers
        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        try:
            # Start hotkey monitoring
            self.hotkey_monitor.start()

            # Start playback loop
            self._playback_task = asyncio.create_task(self._playback_loop())

            # Create and run HTTP server
            app = create_app()
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            server = uvicorn.Server(config)

            logger.info(f"HTTP server starting on http://127.0.0.1:{self.port}")
            await server.serve()

        except Exception as e:
            logger.error(f"Service error: {e}")
            raise

        finally:
            # Cleanup
            self._running = False

            if self._playback_task:
                self._playback_task.cancel()
                try:
                    await self._playback_task
                except asyncio.CancelledError:
                    pass

            self.hotkey_monitor.stop()

            # Remove PID file
            if PID_FILE.exists():
                PID_FILE.unlink()
                logger.info("PID file removed")

            logger.info("Service shutdown complete")
