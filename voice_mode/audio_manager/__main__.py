"""
Entry point for running the Audio Manager service.

Usage:
    python -m voice_mode.audio_manager [--port PORT] [--hotkey HOTKEY]

The service runs an HTTP server that handles audio queuing and playback.
"""

import argparse
import asyncio
import logging
import os
import sys

# Set up logging to stderr (required for MCP compatibility)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("audio_manager")


def main():
    """Main entry point for the audio manager service."""
    parser = argparse.ArgumentParser(description="VoiceMode Audio Manager Service")
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=int(os.getenv("VOICEMODE_AUDIO_MANAGER_PORT", "8881")),
        help="Port to run the HTTP server on (default: 8881)"
    )
    parser.add_argument(
        "--hotkey", "-k",
        type=str,
        default=os.getenv("VOICEMODE_PAUSE_HOTKEY", "fn"),
        choices=["fn", "ctrl", "option", "command", "shift"],
        help="Modifier key that pauses audio when held (default: fn)"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    logger.info(f"Starting Audio Manager on port {args.port}")
    logger.info(f"Pause hotkey: {args.hotkey}")

    # Import here to avoid circular imports
    from .service import AudioManagerService

    service = AudioManagerService(port=args.port, hotkey=args.hotkey)

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Shutting down Audio Manager")
    except Exception as e:
        logger.error(f"Audio Manager error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
