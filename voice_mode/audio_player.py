"""Non-blocking audio player using callback-based playback.

This module provides a queue-based audio playback system that allows multiple
concurrent audio streams without blocking or interference.

Supports pause/resume via a dictation lock file (~/.voicemode/dictating.lock).
When the lock file exists, all audio playback is paused until it's removed.
"""

import logging
import queue
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger("voicemode.audio_player")

# Module-level registry to keep active players alive during non-blocking playback.
# Without this, players can be garbage collected while still playing, causing segfaults.
_active_players: List["NonBlockingAudioPlayer"] = []

# Dictation lock file - when present, audio playback is paused
DICTATING_LOCK_FILE = Path.home() / ".voicemode" / "dictating.lock"


def is_dictating() -> bool:
    """Check if user is currently dictating (function key held).

    Returns:
        True if dictating lock file exists, False otherwise
    """
    return DICTATING_LOCK_FILE.exists()


class NonBlockingAudioPlayer:
    """Non-blocking audio player using callback-based playback.

    This player uses a queue-based callback system to play audio without blocking
    the calling thread. It allows multiple instances to play audio concurrently
    by leveraging the system's audio mixing capabilities (Core Audio on macOS,
    PulseAudio/ALSA on Linux).

    Example:
        player = NonBlockingAudioPlayer()
        player.play(audio_samples, sample_rate=24000)
        player.wait()  # Wait for playback to complete
    """

    def __init__(self, buffer_size: int = 2048, auto_pause_on_dictation: bool = True):
        """Initialize the audio player.

        Args:
            buffer_size: Size of audio buffer chunks for callback (default: 2048)
            auto_pause_on_dictation: If True, automatically pause when dictating lock
                                     file exists (default: True)
        """
        self.buffer_size = buffer_size
        self.audio_queue: Optional[queue.Queue] = None
        self.stream: Optional[sd.OutputStream] = None
        self.playback_complete = threading.Event()
        self.playback_error: Optional[Exception] = None
        self._registered = False
        self._paused = False
        self._pause_lock = threading.Lock()
        self._auto_pause = auto_pause_on_dictation
        self._dictation_monitor: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()

    def _register(self):
        """Register this player to stay alive during non-blocking playback."""
        if not self._registered:
            _active_players.append(self)
            self._registered = True

    def _unregister(self):
        """Unregister this player when playback is done."""
        if self._registered:
            try:
                _active_players.remove(self)
            except ValueError:
                pass
            self._registered = False

    def _audio_callback(self, outdata, frames, time_info, status):
        """Callback function called by sounddevice for each audio buffer.

        Args:
            outdata: Output buffer to fill with audio data
            frames: Number of frames requested
            time_info: Timing information
            status: Status flags
        """
        if status:
            logger.warning(f"Audio callback status: {status}")

        # If paused, output silence but don't consume from queue
        if self._paused:
            outdata[:] = 0
            return

        try:
            # Get audio chunk from queue
            chunk = self.audio_queue.get_nowait()

            # Handle end-of-stream marker
            if chunk is None:
                outdata[:] = 0
                self.playback_complete.set()
                self._unregister()
                raise sd.CallbackStop()

            # Fill output buffer
            chunk_len = len(chunk)
            if chunk_len < frames:
                # Partial chunk - pad with zeros
                if chunk.ndim == 1:
                    # Mono audio - reshape for sounddevice
                    outdata[:chunk_len, 0] = chunk
                    outdata[chunk_len:, 0] = 0
                else:
                    # Multi-channel audio
                    outdata[:chunk_len] = chunk
                    outdata[chunk_len:] = 0
                # Mark playback complete after this chunk
                self.playback_complete.set()
                self._unregister()
                raise sd.CallbackStop()
            else:
                if chunk.ndim == 1:
                    # Mono audio - reshape for sounddevice
                    outdata[:, 0] = chunk[:frames]
                else:
                    # Multi-channel audio
                    outdata[:] = chunk[:frames]

        except queue.Empty:
            # No data available - output silence
            outdata[:] = 0
            logger.debug("Audio queue empty - outputting silence")

    def play(self, samples: np.ndarray, sample_rate: int, blocking: bool = False):
        """Play audio samples using non-blocking callback system.

        Args:
            samples: Audio samples to play (numpy array)
            sample_rate: Sample rate in Hz
            blocking: If True, wait for playback to complete before returning

        Raises:
            Exception: If playback error occurs
        """
        # Reset state
        self.playback_complete.clear()
        self.playback_error = None

        # Ensure samples are float32
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        # Determine number of channels
        if samples.ndim == 1:
            channels = 1
        else:
            channels = samples.shape[1]

        # Create queue and fill with audio chunks
        self.audio_queue = queue.Queue()

        # Split samples into chunks
        for i in range(0, len(samples), self.buffer_size):
            chunk = samples[i:i + self.buffer_size]
            self.audio_queue.put(chunk)

        # Add end-of-stream marker
        self.audio_queue.put(None)

        # Create and start output stream
        try:
            self.stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                callback=self._audio_callback,
                blocksize=self.buffer_size,
                dtype=np.float32
            )
            self.stream.start()

            # Start dictation monitor if enabled (both blocking and non-blocking modes)
            if self._auto_pause:
                self._start_dictation_monitor()

            if blocking:
                self.wait()
            else:
                # Register to stay alive during non-blocking playback.
                # Without this, the player can be garbage collected while
                # the stream is still running, causing a segfault.
                self._register()

        except Exception as e:
            self.playback_error = e
            logger.error(f"Error starting audio playback: {e}")
            raise

    def wait(self, timeout: Optional[float] = None):
        """Wait for playback to complete.

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Raises:
            Exception: If playback error occurred
        """
        # Wait for playback to complete
        if not self.playback_complete.wait(timeout=timeout):
            logger.warning("Playback wait timed out")

        # Stop dictation monitor if running
        self._stop_dictation_monitor()

        # Stop and close stream
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Unregister from active players
        self._unregister()

        # Raise any error that occurred during playback
        if self.playback_error:
            raise self.playback_error

    def stop(self):
        """Stop playback immediately."""
        # Stop dictation monitor if running
        self._stop_dictation_monitor()

        self.playback_complete.set()
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Unregister from active players
        self._unregister()

        # Clear queue
        if self.audio_queue:
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

    def pause(self):
        """Pause audio playback. Audio will output silence until resume() is called."""
        with self._pause_lock:
            if not self._paused:
                self._paused = True
                logger.debug("Audio playback paused")

    def resume(self):
        """Resume audio playback after pause."""
        with self._pause_lock:
            if self._paused:
                self._paused = False
                logger.debug("Audio playback resumed")

    @property
    def is_paused(self) -> bool:
        """Check if playback is currently paused."""
        return self._paused

    def _start_dictation_monitor(self):
        """Start background thread to monitor dictating lock file."""
        import sys
        print("[DICTMON] _start_dictation_monitor called", file=sys.stderr, flush=True)
        if self._dictation_monitor is not None:
            print("[DICTMON] Already running, returning", file=sys.stderr, flush=True)
            return

        self._stop_monitor.clear()

        def monitor_loop():
            print("[DICTMON] monitor_loop started", file=sys.stderr, flush=True)
            was_dictating = False
            loop_count = 0
            while not self._stop_monitor.is_set() and not self.playback_complete.is_set():
                currently_dictating = is_dictating()
                loop_count += 1
                if loop_count % 20 == 1:  # Log every ~1 second
                    print(f"[DICTMON] loop #{loop_count}, dictating={currently_dictating}", file=sys.stderr, flush=True)

                if currently_dictating and not was_dictating:
                    # Started dictating - pause
                    print("[DICTMON] PAUSING - fn pressed", file=sys.stderr, flush=True)
                    self.pause()
                    logger.debug("Dictation detected - pausing audio")
                elif not currently_dictating and was_dictating:
                    # Stopped dictating - resume
                    print("[DICTMON] RESUMING - fn released", file=sys.stderr, flush=True)
                    self.resume()
                    logger.debug("Dictation ended - resuming audio")

                was_dictating = currently_dictating
                self._stop_monitor.wait(timeout=0.05)  # Check every 50ms

        self._dictation_monitor = threading.Thread(target=monitor_loop, daemon=True)
        self._dictation_monitor.start()

    def _stop_dictation_monitor(self):
        """Stop the dictation monitor thread."""
        if self._dictation_monitor is not None:
            self._stop_monitor.set()
            self._dictation_monitor.join(timeout=0.2)
            self._dictation_monitor = None
