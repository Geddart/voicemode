#!/usr/bin/env python3
"""Dictation monitor daemon - pauses VoiceMode audio when function key is held.

This daemon monitors the function key (used by Wispr Flow for dictation) and
creates a lock file when pressed. VoiceMode audio players check this lock file
and pause playback while dictating.

Usage:
    # Run directly
    python -m voice_mode.dictation_monitor

    # Or via uv
    uv run python -m voice_mode.dictation_monitor

Lock file location: ~/.voicemode/dictating.lock

On macOS:
    Uses Quartz Event Tap to monitor the fn key (modifier flag 0x800000).
    Requires Accessibility permissions in System Settings > Privacy & Security.

On other platforms:
    Uses pynput (pip install pynput).
"""

import platform
import signal
import sys
import time
from pathlib import Path

# Lock file location
DICTATING_LOCK_FILE = Path.home() / ".voicemode" / "dictating.lock"


def create_lock():
    """Create the dictating lock file."""
    DICTATING_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    DICTATING_LOCK_FILE.write_text(str(time.time()))
    print(f"  [DEBUG] Lock file created: {DICTATING_LOCK_FILE.exists()}")


def remove_lock():
    """Remove the dictating lock file."""
    try:
        DICTATING_LOCK_FILE.unlink()
        print(f"  [DEBUG] Lock file removed")
    except FileNotFoundError:
        pass


def run_macos_monitor():
    """Run macOS-specific fn key monitor using Quartz Event Tap."""
    try:
        import Quartz
        from AppKit import NSApplication
    except ImportError:
        print("Error: PyObjC is required on macOS. Install with:")
        print("  pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa")
        sys.exit(1)

    print("VoiceMode Dictation Monitor (macOS)")
    print("====================================")
    print(f"Lock file: {DICTATING_LOCK_FILE}")
    print("Monitoring function key (fn)...")
    print("Press Ctrl+C to stop.")
    print()

    # fn key modifier flag on macOS
    NSEventModifierFlagFunction = 0x800000
    fn_pressed = False

    def callback(proxy, event_type, event, refcon):
        nonlocal fn_pressed
        if event_type == Quartz.kCGEventFlagsChanged:
            flags = Quartz.CGEventGetFlags(event)
            fn_now_pressed = bool(flags & NSEventModifierFlagFunction)

            if fn_now_pressed and not fn_pressed:
                fn_pressed = True
                create_lock()
                print("fn pressed - audio paused")
            elif not fn_now_pressed and fn_pressed:
                fn_pressed = False
                remove_lock()
                print("fn released - audio resumed")

        return event

    # Create event tap for flag changes (modifier keys)
    event_mask = (1 << Quartz.kCGEventFlagsChanged)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,  # Don't modify events
        event_mask,
        callback,
        None
    )

    if tap is None:
        print("Error: Could not create event tap.")
        print("Please grant Accessibility permissions in:")
        print("  System Settings > Privacy & Security > Accessibility")
        print("Add Terminal (or your terminal app) to the list.")
        sys.exit(1)

    # Create run loop source and add to current run loop
    run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        run_loop_source,
        Quartz.kCFRunLoopCommonModes
    )

    # Enable the tap
    Quartz.CGEventTapEnable(tap, True)

    print("Event tap active. Listening for fn key...")

    # Run the event loop
    try:
        Quartz.CFRunLoopRun()
    except KeyboardInterrupt:
        pass
    finally:
        remove_lock()
        print("\nStopped.")


def run_pynput_monitor():
    """Run cross-platform monitor using pynput."""
    try:
        from pynput import keyboard
    except ImportError:
        print("Error: pynput is required. Install with: pip install pynput")
        sys.exit(1)

    print("VoiceMode Dictation Monitor")
    print("===========================")
    print(f"Lock file: {DICTATING_LOCK_FILE}")
    print("Monitoring function key (fn)...")
    print("Press Ctrl+C to stop.")
    print()

    fn_pressed = False

    def on_press(key):
        nonlocal fn_pressed
        try:
            if hasattr(keyboard.Key, 'fn') and key == keyboard.Key.fn:
                if not fn_pressed:
                    fn_pressed = True
                    create_lock()
                    print("fn pressed - audio paused")
        except AttributeError:
            pass

    def on_release(key):
        nonlocal fn_pressed
        try:
            if hasattr(keyboard.Key, 'fn') and key == keyboard.Key.fn:
                if fn_pressed:
                    fn_pressed = False
                    remove_lock()
                    print("fn released - audio resumed")
        except AttributeError:
            pass

    remove_lock()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


def main():
    """Run the dictation monitor daemon."""
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nStopping dictation monitor...")
        remove_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Ensure lock is cleaned up on exit
    remove_lock()

    if platform.system() == "Darwin":
        run_macos_monitor()
    else:
        run_pynput_monitor()


if __name__ == "__main__":
    main()
