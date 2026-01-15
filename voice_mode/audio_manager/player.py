"""
Audio playback manager for the Audio Manager service.

Provides audio playback via sounddevice with:
- Blocking playback (waits for completion)
- Pause/resume support
- Playback state tracking
"""

import logging
import queue
import threading
from typing import Optional, Callable

import numpy as np
import sounddevice as sd

logger = logging.getLogger("audio_manager.player")


class AudioPlaybackManager:
    """
    Manages audio playback with pause/resume support.

    Uses sounddevice with callback-based playback to provide:
    - Blocking playback that waits for completion
    - Pause/resume via callbacks
    - State tracking for the service
    """

    def __init__(self, buffer_size: int = 2048):
        self._buffer_size = buffer_size
        self._is_playing = False
        self._is_paused = False
        self._current_project: Optional[str] = None
        self._lock = threading.Lock()
        self._playback_complete = threading.Event()

        # Callbacks for pause state changes
        self._on_pause: Optional[Callable] = None
        self._on_resume: Optional[Callable] = None

        # Audio stream and queue
        self._stream: Optional[sd.OutputStream] = None
        self._audio_queue: Optional[queue.Queue] = None

    def _audio_callback(self, outdata, frames, time_info, status):
        """Callback function called by sounddevice for each audio buffer."""
        if status:
            logger.warning(f"Audio callback status: {status}")

        # If paused, output silence but don't consume from queue
        if self._is_paused:
            outdata[:] = 0
            return

        try:
            # Get audio chunk from queue
            chunk = self._audio_queue.get_nowait()

            # Handle end-of-stream marker
            if chunk is None:
                outdata[:] = 0
                self._playback_complete.set()
                raise sd.CallbackStop()

            # Fill output buffer
            chunk_len = len(chunk)
            if chunk_len < frames:
                # Partial chunk - pad with zeros
                if chunk.ndim == 1:
                    outdata[:chunk_len, 0] = chunk
                    outdata[chunk_len:, 0] = 0
                else:
                    outdata[:chunk_len] = chunk
                    outdata[chunk_len:] = 0
                self._playback_complete.set()
                raise sd.CallbackStop()
            else:
                if chunk.ndim == 1:
                    outdata[:, 0] = chunk[:frames]
                else:
                    outdata[:] = chunk[:frames]

        except queue.Empty:
            # No data available - output silence
            outdata[:] = 0

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
            # Convert bytes to numpy array (16-bit int -> float32)
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            with self._lock:
                self._is_playing = True
                self._current_project = project
                self._playback_complete.clear()

            logger.debug(f"Starting playback for {project}: {len(samples)} samples at {sample_rate}Hz")

            # Determine channels
            channels = 1 if samples.ndim == 1 else samples.shape[1]

            # Create queue and fill with audio chunks
            self._audio_queue = queue.Queue()
            for i in range(0, len(samples), self._buffer_size):
                chunk = samples[i:i + self._buffer_size]
                self._audio_queue.put(chunk)
            self._audio_queue.put(None)  # End-of-stream marker

            # Create and start output stream
            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                callback=self._audio_callback,
                blocksize=self._buffer_size,
                dtype=np.float32
            )
            self._stream.start()

            # Wait for playback to complete
            self._playback_complete.wait()

            # Clean up stream
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

            with self._lock:
                self._is_playing = False
                self._current_project = None

            logger.debug(f"Playback complete for {project}")
            return True

        except Exception as e:
            logger.error(f"Playback error: {e}")
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
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

            # Stop stream
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            # Clear queue
            if self._audio_queue:
                while not self._audio_queue.empty():
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        break

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
