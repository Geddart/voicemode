"""
Audio Router - Unified interface for routing all audio through the audio manager.

All TTS, chimes, and system audio should go through this module.
This ensures proper multi-window coordination and hotkey pause support.
"""

import logging
from typing import Optional

import numpy as np

from .audio_manager.client import AudioManagerClient
from .config import get_project_name, get_session_project_id, SAMPLE_RATE

logger = logging.getLogger("voicemode.audio_router")

# Singleton client instance (reused for efficiency)
_client: Optional[AudioManagerClient] = None


def _get_client() -> AudioManagerClient:
    """Get or create the audio manager client singleton."""
    global _client
    if _client is None:
        _client = AudioManagerClient(auto_start=True)
    return _client


async def play_audio(
    audio_data: bytes,
    sample_rate: int = SAMPLE_RATE,
    project: Optional[str] = None,
    priority: str = "normal",
    blocking: bool = True,
) -> dict:
    """
    Route raw PCM audio bytes through the audio manager.

    Args:
        audio_data: Raw PCM audio bytes (16-bit signed integers)
        sample_rate: Sample rate in Hz (default: 24000)
        project: Project/window name for tracking (auto-detected if None)
        priority: Queue priority ("high", "normal", "low")
        blocking: If True, wait for audio to finish playing

    Returns:
        Dict with queued status, position, item_id, etc.
    """
    client = _get_client()
    result = await client.speak(
        audio_data=audio_data,
        sample_rate=sample_rate,
        project=project or get_session_project_id(),
        priority=priority,
    )

    if blocking and result.get("queued"):
        item_id = result.get("item_id")
        if item_id:
            try:
                await client.wait_for_item(item_id)
            except Exception as e:
                # Audio manager may have crashed - audio may or may not have played
                # Don't re-raise - audio was queued, just couldn't confirm completion
                logger.warning(f"Wait for audio completion failed: {e}")

    return result


async def play_samples(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    project: Optional[str] = None,
    priority: str = "normal",
    blocking: bool = True,
) -> dict:
    """
    Route numpy audio samples through the audio manager.

    Converts float32 samples to 16-bit PCM bytes.

    Args:
        samples: Audio samples as numpy array (float32 in [-1, 1] or int16)
        sample_rate: Sample rate in Hz (default: 24000)
        project: Project/window name for tracking (auto-detected if None)
        priority: Queue priority ("high", "normal", "low")
        blocking: If True, wait for audio to finish playing

    Returns:
        Dict with queued status, position, item_id, etc.
    """
    # Convert to 16-bit PCM bytes
    if samples.dtype == np.float32 or samples.dtype == np.float64:
        # Float samples in range [-1, 1]
        samples_int16 = (samples * 32767).clip(-32768, 32767).astype(np.int16)
    elif samples.dtype == np.int16:
        samples_int16 = samples
    else:
        # Try to convert other types
        samples_int16 = samples.astype(np.int16)

    return await play_audio(
        audio_data=samples_int16.tobytes(),
        sample_rate=sample_rate,
        project=project,
        priority=priority,
        blocking=blocking,
    )


async def reserve_slot(
    project: Optional[str] = None,
    priority: str = "normal",
) -> dict:
    """
    Reserve a queue slot before generating audio.

    Call BEFORE starting TTS generation to ensure proper FIFO ordering
    across multiple concurrent requests from different windows.

    Args:
        project: Project/window name for tracking (auto-detected if None)
        priority: Queue priority ("high", "normal", "low")

    Returns:
        Dict with reserved=True and item_id on success
    """
    client = _get_client()
    return await client.reserve(
        project=project or get_session_project_id(),
        priority=priority,
    )


async def fill_slot(
    item_id: str,
    audio_data: bytes,
    sample_rate: int = SAMPLE_RATE,
    blocking: bool = True,
) -> dict:
    """
    Fill a reserved slot with audio data.

    Call after TTS generation completes with the item_id from reserve_slot().

    Args:
        item_id: The item_id from reserve_slot()
        audio_data: Raw PCM audio bytes (16-bit signed integers)
        sample_rate: Sample rate in Hz (default: 24000)
        blocking: If True, wait for audio to finish playing

    Returns:
        Dict with filled=True on success
    """
    client = _get_client()
    result = await client.fill(
        item_id=item_id,
        audio_data=audio_data,
        sample_rate=sample_rate,
    )

    if blocking and result.get("filled"):
        try:
            await client.wait_for_item(item_id)
        except Exception as e:
            logger.warning(f"Wait for audio completion failed: {e}")

    return result


async def fill_slot_samples(
    item_id: str,
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    blocking: bool = True,
) -> dict:
    """
    Fill a reserved slot with numpy audio samples.

    Converts float32 samples to 16-bit PCM bytes.

    Args:
        item_id: The item_id from reserve_slot()
        samples: Audio samples as numpy array (float32 in [-1, 1] or int16)
        sample_rate: Sample rate in Hz (default: 24000)
        blocking: If True, wait for audio to finish playing

    Returns:
        Dict with filled=True on success
    """
    # Convert to 16-bit PCM bytes
    if samples.dtype == np.float32 or samples.dtype == np.float64:
        samples_int16 = (samples * 32767).clip(-32768, 32767).astype(np.int16)
    elif samples.dtype == np.int16:
        samples_int16 = samples
    else:
        samples_int16 = samples.astype(np.int16)

    return await fill_slot(
        item_id=item_id,
        audio_data=samples_int16.tobytes(),
        sample_rate=sample_rate,
        blocking=blocking,
    )
