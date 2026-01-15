"""
Configurable hotkey monitor for pausing audio during dictation.

Monitors modifier keys (fn, ctrl, option, command, shift) and triggers
callbacks when the configured key is pressed or released.

On macOS, uses Quartz Event Tap for low-level key detection.
On other platforms, falls back to pynput.
"""

import logging
import platform
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("audio_manager.hotkey")

# Lock file for backwards compatibility with existing NonBlockingAudioPlayer
# When hotkey is pressed, we create this file so the old audio player pauses too
DICTATING_LOCK_FILE = Path.home() / ".voicemode" / "dictating.lock"

# Modifier key flag mapping for macOS (Quartz)
MODIFIER_FLAGS = {
    "fn": 0x800000,       # kCGEventFlagMaskSecondaryFn
    "ctrl": 0x40000,      # kCGEventFlagMaskControl
    "option": 0x80000,    # kCGEventFlagMaskAlternate
    "command": 0x100000,  # kCGEventFlagMaskCommand
    "shift": 0x20000,     # kCGEventFlagMaskShift
}

# Human-readable names for logging
MODIFIER_NAMES = {
    "fn": "Function (fn)",
    "ctrl": "Control",
    "option": "Option/Alt",
    "command": "Command",
    "shift": "Shift",
}


class HotkeyMonitor:
    """
    Monitor for configurable modifier key presses.

    Triggers callbacks when the configured modifier key is pressed or released.
    Used to pause audio during dictation with Wispr Flow, Whispering, etc.
    """

    def __init__(
        self,
        hotkey: str = "fn",
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the hotkey monitor.

        Args:
            hotkey: Modifier key to monitor (fn, ctrl, option, command, shift)
            on_press: Callback when key is pressed
            on_release: Callback when key is released
        """
        self._hotkey = hotkey.lower()
        self._on_press = on_press
        self._on_release = on_release
        self._is_pressed = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Validate hotkey
        if self._hotkey not in MODIFIER_FLAGS:
            logger.warning(f"Unknown hotkey '{hotkey}', defaulting to 'fn'")
            self._hotkey = "fn"

        self._flag = MODIFIER_FLAGS[self._hotkey]
        logger.info(f"Hotkey monitor configured for: {MODIFIER_NAMES.get(self._hotkey, self._hotkey)}")

        # Ensure lock file directory exists
        DICTATING_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _create_lock_file(self):
        """Create lock file for backwards compatibility with existing audio player."""
        try:
            DICTATING_LOCK_FILE.write_text(f"hotkey:{self._hotkey}")
            logger.debug(f"Created lock file: {DICTATING_LOCK_FILE}")
        except Exception as e:
            logger.error(f"Failed to create lock file: {e}")

    def _remove_lock_file(self):
        """Remove lock file."""
        try:
            if DICTATING_LOCK_FILE.exists():
                DICTATING_LOCK_FILE.unlink()
                logger.debug(f"Removed lock file: {DICTATING_LOCK_FILE}")
        except Exception as e:
            logger.error(f"Failed to remove lock file: {e}")

    def start(self) -> bool:
        """
        Start monitoring for hotkey presses.

        Returns:
            True if monitoring started successfully
        """
        if self._running:
            logger.warning("Hotkey monitor already running")
            return True

        self._running = True

        if platform.system() == "Darwin":
            self._thread = threading.Thread(target=self._run_macos, daemon=True)
        else:
            self._thread = threading.Thread(target=self._run_pynput, daemon=True)

        self._thread.start()
        logger.info("Hotkey monitor started")
        return True

    def stop(self):
        """Stop monitoring for hotkey presses."""
        self._running = False
        if self._thread:
            # Thread is daemon, will stop with process
            self._thread = None
        logger.info("Hotkey monitor stopped")

    def _run_macos(self):
        """Run hotkey monitoring on macOS using Quartz Event Tap."""
        try:
            import Quartz
            from Cocoa import NSApplication
        except ImportError:
            logger.error("Quartz/Cocoa not available. Install with: pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa")
            return

        def callback(proxy, event_type, event, refcon):
            """Quartz event tap callback."""
            if not self._running:
                return event

            if event_type == Quartz.kCGEventFlagsChanged:
                flags = Quartz.CGEventGetFlags(event)
                now_pressed = bool(flags & self._flag)

                if now_pressed and not self._is_pressed:
                    self._is_pressed = True
                    logger.debug(f"Hotkey pressed: {self._hotkey}")
                    # Create lock file for backwards compatibility
                    self._create_lock_file()
                    if self._on_press:
                        try:
                            self._on_press()
                        except Exception as e:
                            logger.error(f"Error in on_press callback: {e}")

                elif not now_pressed and self._is_pressed:
                    self._is_pressed = False
                    logger.debug(f"Hotkey released: {self._hotkey}")
                    # Remove lock file
                    self._remove_lock_file()
                    if self._on_release:
                        try:
                            self._on_release()
                        except Exception as e:
                            logger.error(f"Error in on_release callback: {e}")

            return event

        # Create event tap for modifier key changes
        event_mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            event_mask,
            callback,
            None
        )

        if tap is None:
            logger.error(
                "Could not create event tap. "
                "Please grant Accessibility permissions in "
                "System Settings > Privacy & Security > Accessibility"
            )
            return

        # Create run loop source
        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            run_loop_source,
            Quartz.kCFRunLoopCommonModes
        )

        # Enable the tap
        Quartz.CGEventTapEnable(tap, True)

        logger.info("macOS event tap created successfully")

        # Run the event loop
        while self._running:
            # Run for a short interval then check if we should stop
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.5, False)

        logger.info("macOS event tap stopped")

    def _run_pynput(self):
        """Fallback hotkey monitoring using pynput (cross-platform)."""
        try:
            from pynput import keyboard
        except ImportError:
            logger.error("pynput not available. Install with: pip install pynput")
            return

        # Map our hotkey names to pynput keys
        key_map = {
            "ctrl": keyboard.Key.ctrl,
            "option": keyboard.Key.alt,
            "command": keyboard.Key.cmd,
            "shift": keyboard.Key.shift,
            # Note: fn key is not reliably detectable via pynput on most systems
            "fn": None,
        }

        target_key = key_map.get(self._hotkey)
        if target_key is None:
            logger.warning(f"Key '{self._hotkey}' not supported via pynput. Monitoring disabled.")
            return

        def on_press(key):
            if not self._running:
                return False  # Stop listener
            if key == target_key and not self._is_pressed:
                self._is_pressed = True
                logger.debug(f"Hotkey pressed: {self._hotkey}")
                if self._on_press:
                    try:
                        self._on_press()
                    except Exception as e:
                        logger.error(f"Error in on_press callback: {e}")

        def on_release(key):
            if not self._running:
                return False  # Stop listener
            if key == target_key and self._is_pressed:
                self._is_pressed = False
                logger.debug(f"Hotkey released: {self._hotkey}")
                if self._on_release:
                    try:
                        self._on_release()
                    except Exception as e:
                        logger.error(f"Error in on_release callback: {e}")

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            while self._running:
                listener.join(timeout=0.5)

        logger.info("pynput listener stopped")

    @property
    def is_pressed(self) -> bool:
        """Check if the hotkey is currently pressed."""
        return self._is_pressed

    @property
    def hotkey(self) -> str:
        """Get the configured hotkey name."""
        return self._hotkey

    def get_status(self) -> dict:
        """Get hotkey monitor status."""
        return {
            "hotkey": self._hotkey,
            "hotkey_name": MODIFIER_NAMES.get(self._hotkey, self._hotkey),
            "is_pressed": self._is_pressed,
            "running": self._running,
        }
