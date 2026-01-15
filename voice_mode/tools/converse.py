"""Conversation tools for text-to-speech interactions.

This module provides TTS-only functionality for speaking messages.
All STT (speech-to-text) functionality has been removed.
"""

import asyncio
import logging
import os
import time
import traceback
from typing import Optional, Literal
from pathlib import Path
from datetime import datetime

import numpy as np

from voice_mode.server import mcp
from voice_mode.conversation_logger import get_conversation_logger
from voice_mode.config import (
    audio_operation_lock,
    DEBUG,
    OPENAI_API_KEY,
    SKIP_TTS,
    TTS_SPEED,
    METRICS_LEVEL,
)
import voice_mode.config
from voice_mode.provider_discovery import provider_registry
from voice_mode.core import (
    get_openai_clients,
    text_to_speech,
    cleanup as cleanup_clients,
)
from voice_mode.statistics_tracking import track_voice_interaction
from voice_mode.utils import (
    get_event_logger,
    log_tool_request_start,
    log_tool_request_end
)

logger = logging.getLogger("voicemode")


# DJ Ducking Configuration
DJ_SOCKET_PATH = "/tmp/voicemode-mpv.sock"
DJ_VOLUME_DUCK_AMOUNT = int(os.environ.get("VOICEMODE_DJ_DUCK_AMOUNT", "20"))


def _dj_command(cmd: str) -> Optional[str]:
    """Send a command to MPV socket if it exists.

    Returns the response or None if socket doesn't exist.
    """
    import socket
    import json

    if not os.path.exists(DJ_SOCKET_PATH):
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(DJ_SOCKET_PATH)

        # MPV expects JSON commands followed by newline
        sock.send((json.dumps({"command": cmd.split()}) + "\n").encode())

        # Read response
        response = sock.recv(1024).decode()
        sock.close()

        return response
    except (socket.error, socket.timeout, ConnectionRefusedError):
        return None


def get_dj_volume() -> Optional[float]:
    """Get current DJ volume level (0-100) or None if not available."""
    response = _dj_command("get_property volume")
    if response:
        import json
        try:
            data = json.loads(response)
            if "data" in data:
                return float(data["data"])
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return None


def set_dj_volume(volume: float) -> bool:
    """Set DJ volume level (0-100). Returns True if successful."""
    response = _dj_command(f"set_property volume {volume}")
    return response is not None


class DJDucker:
    """Context manager for temporarily reducing DJ volume during TTS playback."""

    def __init__(self):
        self.original_volume = None

    def __enter__(self):
        self.original_volume = get_dj_volume()
        if self.original_volume is not None:
            # Duck the volume
            ducked_volume = max(0, self.original_volume - DJ_VOLUME_DUCK_AMOUNT)
            if set_dj_volume(ducked_volume):
                logger.debug(f"DJ ducked: {self.original_volume:.0f} -> {ducked_volume:.0f}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.original_volume is not None:
            # Restore original volume
            if set_dj_volume(self.original_volume):
                logger.debug(f"DJ restored: {self.original_volume:.0f}")
        return False


# Track last session end time for measuring AI thinking time
last_session_end_time = None

# Initialize OpenAI clients - now using provider registry for endpoint discovery
openai_clients = get_openai_clients(OPENAI_API_KEY or "dummy-key-for-local", None)


async def startup_initialization():
    """Initialize services on startup based on configuration"""
    if voice_mode.config._startup_initialized:
        return

    voice_mode.config._startup_initialized = True
    logger.info("Running startup initialization...")

    # Log provider registry status
    await provider_registry.discover_providers()
    logger.info("Provider discovery complete")


async def get_tts_config(
    provider: Optional[str] = None,
    voice: Optional[str] = None,
    model: Optional[str] = None,
    instructions: Optional[str] = None
):
    """Get TTS configuration from provider registry."""
    from voice_mode.providers import get_tts_client_and_voice

    # Use provider registry to get TTS client and voice
    client, selected_voice, base_url, provider_info = await get_tts_client_and_voice(
        voice=voice,
        model=model,
        base_url=None
    )

    return {
        "client": client,
        "voice": selected_voice,
        "model": model or "tts-1",
        "base_url": base_url,
        "provider": provider_info.get("provider") if provider_info else None,
        "provider_type": provider_info.get("provider_type") if provider_info else None,
        "instructions": instructions
    }


async def text_to_speech_with_failover(
    message: str,
    voice: Optional[str] = None,
    model: Optional[str] = None,
    instructions: Optional[str] = None,
    audio_format: Optional[str] = None,
    initial_provider: Optional[str] = None,
    speed: Optional[float] = None,
    background: bool = False
):
    """Generate TTS with failover between providers.

    Returns:
        Tuple of (success, metrics_dict, config_dict)
    """
    from voice_mode.simple_failover import simple_tts_failover

    return await simple_tts_failover(
        message=message,
        voice=voice,
        model=model,
        instructions=instructions,
        audio_format=audio_format,
        initial_provider=initial_provider,
        speed=speed,
        background=background
    )


async def _run_tts_in_background(
    message: str,
    voice: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_instructions: Optional[str] = None,
    audio_format: Optional[str] = None,
    tts_provider: Optional[str] = None,
    speed: Optional[float] = None,
):
    """Run TTS in background without blocking.

    This is spawned as an independent asyncio task and handles its own
    audio coordination through the audio manager.
    """
    try:
        logger.info(f"Background TTS starting: '{message[:50]}...'")

        # Run TTS with blocking=False (audio manager handles queuing)
        success, metrics, config = await text_to_speech_with_failover(
            message=message,
            voice=voice,
            model=tts_model,
            instructions=tts_instructions,
            audio_format=audio_format,
            initial_provider=tts_provider,
            speed=speed,
            background=False  # Let audio manager handle queuing
        )

        if success:
            logger.info("Background TTS completed successfully")
        else:
            logger.error("Background TTS failed")

    except Exception as e:
        logger.error(f"Background TTS error: {e}")
        if DEBUG:
            logger.error(traceback.format_exc())


@mcp.tool()
async def converse(
    message: str,
    voice: Optional[str] = None,
    tts_provider: Optional[Literal["openai", "kokoro"]] = None,
    speed: Optional[float] = None,
    tts_model: Optional[str] = None,
    tts_instructions: Optional[str] = None,
    background: bool = True,
    queue: bool = True
) -> str:
    """Speak a message using text-to-speech.

    Args:
        message: Text to speak (required)
        voice: TTS voice name (auto-selected if not specified)
        speed: Speech rate 0.25-4.0 (default: 1.0)
        tts_provider: "openai" or "kokoro" (auto-selected if not specified)
        background: If True, start playback and return immediately (default: True).
                   Audio plays while Claude continues working. Set to False to wait.
        queue: If True, wait for other audio to finish before playing (default: True).
               When queued, announces which project the message is from.
    """
    # Determine whether to skip TTS
    should_skip_tts = SKIP_TTS

    # Convert string speed to float
    if speed is not None and isinstance(speed, str):
        try:
            speed = float(speed)
        except ValueError:
            return f"❌ Error: speed must be a number (got '{speed}')"

    # Apply default speed from config if not provided
    speed_from_config = False
    if speed is None:
        speed = TTS_SPEED
        speed_from_config = True

    # Validate speed parameter range
    if speed is not None:
        if not (0.25 <= speed <= 4.0):
            source = " from VOICEMODE_TTS_SPEED environment variable" if speed_from_config else ""
            return f"❌ Error: speed must be between 0.25 and 4.0 (got {speed}{source})"

    # Determine effective metrics level
    effective_metrics_level = METRICS_LEVEL

    logger.info(f"Converse: '{message[:50]}{'...' if len(message) > 50 else ''}'")

    # Check if FFmpeg is available
    ffmpeg_available = getattr(voice_mode.config, 'FFMPEG_AVAILABLE', True)
    if not ffmpeg_available:
        from ..utils.ffmpeg_check import get_install_instructions
        error_msg = (
            "FFmpeg is required for voice features but is not installed.\n\n"
            f"{get_install_instructions()}\n\n"
            "Voice features cannot work without FFmpeg."
        )
        logger.error(error_msg)
        return f"❌ Error: {error_msg}"

    # Run startup initialization if needed
    await startup_initialization()

    # Refresh audio device cache to pick up any device changes
    import sounddevice as sd
    sd._terminate()
    sd._initialize()

    # Get event logger
    event_logger = get_event_logger()

    # Log tool request start
    if event_logger:
        log_tool_request_start("converse", {"background": background})

    # Track execution time
    start_time = time.time()
    if DEBUG:
        import resource
        start_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    result = None
    success = False

    try:
        # Handle background mode: spawn TTS as independent task and return immediately
        if background and not should_skip_tts:
            asyncio.create_task(_run_tts_in_background(
                message=message,
                voice=voice,
                tts_model=tts_model,
                tts_instructions=tts_instructions,
                audio_format=None,
                tts_provider=tts_provider,
                speed=speed,
            ))
            logger.info("TTS spawned in background, returning immediately")
            return "✓ Speaking in background"

        # Blocking mode: wait for TTS to complete
        timings = {}

        try:
            async with audio_operation_lock:
                tts_start = time.perf_counter()

                if should_skip_tts:
                    tts_success = True
                    tts_metrics = {'ttfa': 0, 'generation': 0, 'playback': 0, 'total': 0}
                    tts_config = {'provider': 'no-op', 'voice': 'none'}
                else:
                    # Duck DJ volume during TTS playback
                    with DJDucker():
                        tts_success, tts_metrics, tts_config = await text_to_speech_with_failover(
                            message=message,
                            voice=voice,
                            model=tts_model,
                            instructions=tts_instructions,
                            audio_format=None,
                            initial_provider=tts_provider,
                            speed=speed,
                            background=background
                        )

                # Record timings
                if tts_metrics:
                    timings['ttfa'] = tts_metrics.get('ttfa', 0)
                    timings['tts_gen'] = tts_metrics.get('generation', 0)
                    timings['tts_play'] = tts_metrics.get('playback', 0)
                timings['tts_total'] = time.perf_counter() - tts_start

                # Log TTS to conversation log
                if tts_success:
                    try:
                        tts_timing_parts = []
                        if 'ttfa' in timings:
                            tts_timing_parts.append(f"ttfa {timings['ttfa']:.1f}s")
                        if 'tts_gen' in timings:
                            tts_timing_parts.append(f"gen {timings['tts_gen']:.1f}s")
                        if 'tts_play' in timings:
                            tts_timing_parts.append(f"play {timings['tts_play']:.1f}s")
                        tts_timing_str = ", ".join(tts_timing_parts) if tts_timing_parts else None

                        conversation_logger = get_conversation_logger()
                        conversation_logger.log_tts(
                            text=message,
                            audio_file=os.path.basename(tts_metrics.get('audio_path')) if tts_metrics and tts_metrics.get('audio_path') else None,
                            model=tts_config.get('model') if tts_config else tts_model,
                            voice=tts_config.get('voice') if tts_config else voice,
                            provider=tts_config.get('provider') if tts_config else (tts_provider if tts_provider else 'openai'),
                            provider_url=tts_config.get('base_url') if tts_config else None,
                            provider_type=tts_config.get('provider_type') if tts_config else None,
                            is_fallback=tts_config.get('is_fallback', False) if tts_config else False,
                            fallback_reason=tts_config.get('fallback_reason') if tts_config else None,
                            timing=tts_timing_str,
                            time_to_first_audio=timings.get('ttfa') if timings else None,
                            generation_time=timings.get('tts_gen') if timings else None,
                            playback_time=timings.get('tts_play') if timings else None,
                        )
                    except Exception as e:
                        logger.error(f"Failed to log TTS to JSONL: {e}")

                if not tts_success:
                    # Handle TTS failure
                    if tts_config and tts_config.get('error_type') == 'all_providers_failed':
                        error_lines = ["Error: Could not speak message. TTS service connection failed:"]
                        for attempt in tts_config.get('attempted_endpoints', []):
                            endpoint_or_provider = attempt.get('endpoint', attempt.get('provider', 'unknown'))
                            error_lines.append(f"  - {endpoint_or_provider}: {attempt['error']}")
                        result = "\n".join(error_lines)
                    else:
                        result = "Error: Could not speak message. All TTS providers failed."
                    return result

                # Format timing info
                timing_info = ""
                is_background = tts_metrics.get('background', False) if tts_metrics else False
                if tts_success and tts_metrics:
                    if is_background:
                        timing_info = f" (gen: {tts_metrics.get('generation', 0):.1f}s, playing in background)"
                    else:
                        timing_info = f" (gen: {tts_metrics.get('generation', 0):.1f}s, play: {tts_metrics.get('playback', 0):.1f}s)"

                # Track statistics
                timing_str = ""
                if tts_success and timings:
                    timing_parts = []
                    if 'ttfa' in timings:
                        timing_parts.append(f"ttfa {timings['ttfa']:.1f}s")
                    if 'tts_gen' in timings:
                        timing_parts.append(f"tts_gen {timings['tts_gen']:.1f}s")
                    if 'tts_play' in timings:
                        timing_parts.append(f"tts_play {timings['tts_play']:.1f}s")
                    timing_str = ", ".join(timing_parts)

                track_voice_interaction(
                    message=message,
                    response="[speak-only]",
                    timing_str=timing_str,
                    transport="speak-only",
                    voice_provider=tts_provider,
                    voice_name=voice,
                    model=tts_model,
                    success=tts_success,
                    error_message=None if tts_success else "TTS failed"
                )

                # Format result
                if effective_metrics_level == "minimal":
                    if is_background:
                        result = "✓ Speaking in background"
                    else:
                        result = "✓ Message spoken successfully"
                else:
                    if is_background:
                        result = f"✓ Speaking in background{timing_info}"
                    else:
                        result = f"✓ Message spoken successfully{timing_info}"

                success = True
                logger.info(f"Result: {result}")
                return result

        except Exception as e:
            logger.error(f"TTS error: {e}")
            if DEBUG:
                logger.error(f"Traceback: {traceback.format_exc()}")

            track_voice_interaction(
                message=message,
                response="[error]",
                timing_str=None,
                transport="speak-only",
                voice_provider=tts_provider,
                voice_name=voice,
                model=tts_model,
                success=False,
                error_message=str(e)
            )

            result = f"Error: {str(e)}"
            return result

    except Exception as e:
        logger.error(f"Unexpected error in converse: {e}")
        if DEBUG:
            logger.error(f"Full traceback: {traceback.format_exc()}")
        result = f"Unexpected error: {str(e)}"
        return result

    finally:
        # Log tool request end
        if event_logger:
            log_tool_request_end("converse", success=success)

        # Log execution metrics
        elapsed = time.time() - start_time
        logger.info(f"Converse completed in {elapsed:.2f}s")

        if DEBUG:
            import resource
            import gc
            end_memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            memory_delta = end_memory - start_memory
            logger.debug(f"Memory delta: {memory_delta} KB")
            collected = gc.collect()
            logger.debug(f"Garbage collected {collected} objects")
