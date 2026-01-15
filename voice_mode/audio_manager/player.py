"""
Audio playback manager for the Audio Manager service.

Wraps the existing NonBlockingAudioPlayer to provide:
- Blocking playback (waits for completion)
- Pause/resume support
- Playback state tracking
"""

import logging
import threading
import time
from typing import Optional, Callable

import numpy as np

logger = logging.getLogger("audio_manager.player")


class AudioPlaybackManager:
    """
    Manages audio playback with pause/resume support.

    This class wraps sounddevice for audio output, providing:
    - Blocking playback that waits for completion
    - Pause/resume via callbacks
    - State tracking for the service
    """

    def __init__(self):
        self._is_playing = False
        self._is_paused = False
        self._current_project: Optional[str] = None
        self._lock = threading.Lock()
        self._playback_complete = threading.Event()

        # Callbacks for pause state changes
        self._on_pause: Optional[Callable] = None
        self._on_resume: Optional[Callable] = None

        # Player instance (lazily created)
        self._player = None

    def play(
        self,
        audio_data: bytes,
        sample_rate: int,
        project: str = "unknown"
    ) -> bool:
        """
        Play audio and block until complete.

        Args:
            audio_data: Raw audio bytes (16-bit signed integers)
            sample_rate: Sample rate in Hz
            project: Project name for tracking

        Returns:
            True if playback completed successfully, False otherwise
        """
        try:
            # Convert bytes to numpy array
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            with self._lock:
                self._is_playing = True
                self._current_project = project
                self._playback_complete.clear()

            logger.debug(f"Starting playback for {project}: {len(samples)} samples at {sample_rate}Hz")

            # Use NonBlockingAudioPlayer for actual playback
            from voice_mode.audio_player import NonBlockingAudioPlayer

            self._player = NonBlockingAudioPlayer()

            # Set up pause/resume handling
            if hasattr(self._player, '_paused'):
                self._player._paused = self._is_paused

            # Play with blocking=True to wait for completion
            self._player.play(samples, sample_rate, blocking=False)

            # Wait for playback to complete, checking pause state periodically
            while not self._player.playback_complete.is_set():
                # Update pause state on the player
                if self._player and hasattr(self._player, '_paused'):
                    with self._lock:
                        self._player._paused = self._is_paused

                self._player.playback_complete.wait(timeout=0.05)

            # Clean up
            self._player.wait(timeout=1.0)
            self._player = None

            with self._lock:
                self._is_playing = False
                self._current_project = None
                self._playback_complete.set()

            logger.debug(f"Playback complete for {project}")
            return True

        except Exception as e:
            logger.error(f"Playback error: {e}")
            with self._lock:
                self._is_playing = False
                self._current_project = None
                self._playback_complete.set()
            return False

    def pause(self) -> bool:
        """
        Pause current playback (or set paused state for future playback).

        Always sets _is_paused=True, even if nothing is currently playing.
        This ensures audio that arrives later will start paused.

        Returns:
            True (always succeeds)
        """
        with self._lock:
            self._is_paused = True

            # Update player if active
            if self._player and hasattr(self._player, 'pause'):
                self._player.pause()

        logger.debug("Paused state set")
        if self._on_pause:
            self._on_pause()
        return True

    def resume(self) -> bool:
        """
        Resume paused playback (or clear paused state).

        Always sets _is_paused=False, even if nothing is currently playing.
        This ensures audio that arrives later will play immediately.

        Returns:
            True (always succeeds)
        """
        with self._lock:
            self._is_paused = False

            # Update player if active
            if self._player and hasattr(self._player, 'resume'):
                self._player.resume()

        logger.debug("Resumed state set")
        if self._on_resume:
            self._on_resume()
        return True

    def stop(self) -> bool:
        """
        Stop current playback.

        Returns:
            True if stop was applied
        """
        with self._lock:
            if not self._is_playing:
                return False

            if self._player and hasattr(self._player, 'stop'):
                self._player.stop()

            self._is_playing = False
            self._is_paused = False
            self._current_project = None
            self._playback_complete.set()

        logger.debug("Playback stopped")
        return True

    def set_pause_callbacks(
        self,
        on_pause: Optional[Callable] = None,
        on_resume: Optional[Callable] = None
    ):
        """Set callbacks for pause/resume events."""
        self._on_pause = on_pause
        self._on_resume = on_resume

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._lock:
            return self._is_playing

    @property
    def is_paused(self) -> bool:
        """Check if playback is paused."""
        with self._lock:
            return self._is_paused

    @property
    def current_project(self) -> Optional[str]:
        """Get the project name of currently playing audio."""
        with self._lock:
            return self._current_project

    def get_status(self) -> dict:
        """Get playback status."""
        with self._lock:
            return {
                "playing": self._is_playing,
                "paused": self._is_paused,
                "current_project": self._current_project,
            }
