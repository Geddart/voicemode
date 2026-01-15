"""
Streaming audio playback for voice-mode.

This module provides audio download and routing through the audio manager
for proper multi-window coordination and hotkey pause support.
"""

import asyncio
import io
import time
from typing import Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import numpy as np

from pydub import AudioSegment

from .config import (
    STREAM_CHUNK_SIZE,
    SAMPLE_RATE,
    logger
)
from .utils import get_event_logger
from . import audio_router


@dataclass
class StreamMetrics:
    """Metrics for streaming playback performance."""
    ttfa: float = 0.0  # Time to first audio
    generation_time: float = 0.0
    playback_time: float = 0.0
    buffer_underruns: int = 0
    chunks_received: int = 0
    chunks_played: int = 0
    audio_path: Optional[str] = None  # Path to saved audio file


async def stream_pcm_audio(
    text: str,
    openai_client,
    request_params: dict,
    debug: bool = False,
    save_audio: bool = False,
    audio_dir: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    blocking: bool = True,
    item_id: Optional[str] = None,
) -> Tuple[bool, StreamMetrics]:
    """Stream PCM audio - buffers chunks then routes through audio manager.

    All audio is routed through the centralized audio manager for proper
    multi-window coordination and hotkey pause support.

    Args:
        item_id: Pre-reserved queue slot ID. If provided, fills that slot
                 instead of creating a new queue entry.
    """
    metrics = StreamMetrics()
    start_time = time.perf_counter()
    first_chunk_time = None
    audio_buffer = io.BytesIO()

    try:
        # Log TTS playback start
        event_logger = get_event_logger()
        if event_logger:
            event_logger.log_event(event_logger.TTS_PLAYBACK_START)

        logger.info("Starting PCM audio download with buffering")

        # Use the streaming response API to download audio
        async with openai_client.audio.speech.with_streaming_response.create(
            **request_params
        ) as response:
            chunk_count = 0
            bytes_received = 0

            # Buffer chunks as they arrive
            async for chunk in response.iter_bytes(chunk_size=STREAM_CHUNK_SIZE):
                if chunk:
                    # Track first chunk received
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter()
                        chunk_receive_time = first_chunk_time - start_time
                        logger.info(f"First audio chunk received after {chunk_receive_time:.3f}s")

                        # Log TTS first audio event
                        if event_logger:
                            event_logger.log_event(event_logger.TTS_FIRST_AUDIO)

                    audio_buffer.write(chunk)

                    chunk_count += 1
                    bytes_received += len(chunk)
                    metrics.chunks_received = chunk_count

                    if debug and chunk_count % 10 == 0:
                        logger.debug(f"Buffered {chunk_count} chunks, {bytes_received} bytes")

        download_time = time.perf_counter()
        metrics.generation_time = download_time - start_time
        metrics.ttfa = first_chunk_time - start_time if first_chunk_time else 0

        logger.info(f"Download complete - {bytes_received} bytes in {metrics.generation_time:.3f}s")

        # Route audio through audio manager
        audio_buffer.seek(0)
        audio_data = audio_buffer.read()

        if audio_data:
            # Route through audio manager (handles multi-window coordination and pause)
            if item_id:
                # Fill the pre-reserved slot
                result = await audio_router.fill_slot(
                    item_id=item_id,
                    audio_data=audio_data,
                    sample_rate=SAMPLE_RATE,
                    blocking=blocking,
                )
                if result.get("filled"):
                    metrics.chunks_played = chunk_count
                    logger.info(f"Filled reserved slot {item_id}")
                else:
                    logger.error(f"Failed to fill slot: {result.get('error', 'unknown')}")
                    return False, metrics
            else:
                # No reservation - direct queue
                result = await audio_router.play_audio(
                    audio_data=audio_data,
                    sample_rate=SAMPLE_RATE,
                    priority="normal",
                    blocking=blocking,
                )
                if result.get("queued"):
                    metrics.chunks_played = chunk_count
                    logger.info(f"Audio queued for playback, position: {result.get('position', 0)}")
                else:
                    logger.error(f"Failed to queue audio: {result.get('error', 'unknown')}")
                    return False, metrics

        end_time = time.perf_counter()
        metrics.playback_time = end_time - start_time

        # Log TTS playback end with metrics
        if event_logger:
            tts_event_data = {
                "metrics": {
                    "ttfa_ms": round(metrics.ttfa * 1000, 1),
                    "total_time_ms": round(metrics.playback_time * 1000, 1),
                    "bytes_received": bytes_received,
                    "chunks": chunk_count,
                    "format": "pcm",
                    "sample_rate_hz": SAMPLE_RATE
                }
            }
            event_logger.log_event(event_logger.TTS_PLAYBACK_END, tts_event_data)

        logger.info(f"Streaming complete - TTFA: {metrics.ttfa:.3f}s, "
                   f"Total: {metrics.playback_time:.3f}s, "
                   f"Chunks: {metrics.chunks_received}")

        # Save audio if enabled
        if save_audio and audio_dir and audio_data:
            try:
                from .core import save_debug_file
                # PCM format needs special handling - save as WAV
                import wave
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
                    with wave.open(tmp_wav.name, 'wb') as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)  # 16-bit
                        wav_file.setframerate(SAMPLE_RATE)
                        wav_file.writeframes(audio_data)
                    # Read back the WAV file
                    with open(tmp_wav.name, 'rb') as f:
                        wav_data = f.read()
                    import os
                    os.unlink(tmp_wav.name)
                    audio_path = save_debug_file(wav_data, "tts", "wav", audio_dir, True, conversation_id)
                    if audio_path:
                        logger.info(f"TTS audio saved to: {audio_path}")
                        metrics.audio_path = audio_path
            except Exception as e:
                logger.error(f"Failed to save TTS audio: {e}")

        return True, metrics

    except Exception as e:
        logger.error(f"PCM streaming failed: {e}")
        return False, metrics


async def stream_tts_audio(
    text: str,
    openai_client,
    request_params: dict,
    debug: bool = False,
    save_audio: bool = False,
    audio_dir: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    blocking: bool = True,
    item_id: Optional[str] = None,
) -> Tuple[bool, StreamMetrics]:
    """Stream TTS audio - buffers then routes through audio manager.

    All audio is routed through the centralized audio manager for proper
    multi-window coordination and hotkey pause support.

    Args:
        text: Text to convert to speech
        openai_client: OpenAI client instance
        request_params: Parameters for TTS request
        debug: Enable debug logging
        save_audio: Save audio to disk
        audio_dir: Directory for saved audio
        conversation_id: Conversation ID for logging
        blocking: If True, wait for audio to finish playing
        item_id: Pre-reserved queue slot ID for FIFO ordering

    Returns:
        Tuple of (success, metrics)
    """
    format = request_params.get('response_format', 'pcm')
    logger.info(f"Starting TTS with format: {format}, blocking: {blocking}")

    # PCM is best for streaming (no decoding needed)
    # For other formats, we may need buffering
    if format == 'pcm':
        return await stream_pcm_audio(
            text=text,
            openai_client=openai_client,
            request_params=request_params,
            debug=debug,
            save_audio=save_audio,
            audio_dir=audio_dir,
            conversation_id=conversation_id,
            blocking=blocking,
            item_id=item_id,
        )
    else:
        # Use buffered streaming for formats that need decoding
        return await stream_with_buffering(
            text=text,
            openai_client=openai_client,
            request_params=request_params,
            debug=debug,
            save_audio=save_audio,
            audio_dir=audio_dir,
            conversation_id=conversation_id,
            blocking=blocking,
            item_id=item_id,
        )


# Fallback for complex formats - buffer and decode complete file
async def stream_with_buffering(
    text: str,
    openai_client,
    request_params: dict,
    sample_rate: int = SAMPLE_RATE,
    debug: bool = False,
    save_audio: bool = False,
    audio_dir: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    blocking: bool = True,
    item_id: Optional[str] = None,
) -> Tuple[bool, StreamMetrics]:
    """Buffer audio then route through audio manager.

    This is used for formats like MP3, Opus, etc where frame boundaries are critical.
    Downloads complete audio, decodes to PCM, and routes through audio manager.

    All audio is routed through the centralized audio manager for proper
    multi-window coordination and hotkey pause support.

    Args:
        item_id: Pre-reserved queue slot ID for FIFO ordering
    """
    format = request_params.get('response_format', 'pcm')
    logger.info(f"Using buffered streaming for format: {format}, blocking: {blocking}")

    metrics = StreamMetrics()
    start_time = time.perf_counter()
    first_chunk_time = None

    # Buffer for accumulating chunks
    audio_buffer = io.BytesIO()

    try:
        # Log TTS playback start
        event_logger = get_event_logger()
        if event_logger:
            event_logger.log_event(event_logger.TTS_PLAYBACK_START)

        # Use the streaming response API to download audio
        async with openai_client.audio.speech.with_streaming_response.create(
            **request_params
        ) as response:
            bytes_received = 0

            # Download chunks
            async for chunk in response.iter_bytes(chunk_size=STREAM_CHUNK_SIZE):
                if chunk:
                    # Track first chunk for TTFA
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter()
                        logger.info(f"First chunk received after {first_chunk_time - start_time:.3f}s")

                        if event_logger:
                            event_logger.log_event(event_logger.TTS_FIRST_AUDIO)

                    audio_buffer.write(chunk)
                    metrics.chunks_received += 1
                    bytes_received += len(chunk)

                    if debug and metrics.chunks_received % 10 == 0:
                        logger.debug(f"Buffered {metrics.chunks_received} chunks, {bytes_received} bytes")

        download_time = time.perf_counter()
        metrics.generation_time = download_time - start_time
        metrics.ttfa = first_chunk_time - start_time if first_chunk_time else 0

        logger.info(f"Download complete - {bytes_received} bytes in {metrics.generation_time:.3f}s")

        # Decode to PCM samples
        audio_buffer.seek(0)
        try:
            audio = AudioSegment.from_file(audio_buffer, format=format)
            # Convert to mono if stereo
            if audio.channels > 1:
                audio = audio.set_channels(1)
            # Get raw samples as int16
            samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
            pcm_data = samples.tobytes()
            decoded_sample_rate = audio.frame_rate

            logger.info(f"Decoded {len(pcm_data)} bytes of PCM audio at {decoded_sample_rate}Hz")
        except Exception as e:
            logger.error(f"Failed to decode audio: {e}")
            return False, metrics

        # Route through audio manager
        if pcm_data:
            if item_id:
                # Fill the pre-reserved slot
                result = await audio_router.fill_slot(
                    item_id=item_id,
                    audio_data=pcm_data,
                    sample_rate=decoded_sample_rate,
                    blocking=blocking,
                )
                if result.get("filled"):
                    metrics.chunks_played = metrics.chunks_received
                    logger.info(f"Filled reserved slot {item_id}")
                else:
                    logger.error(f"Failed to fill slot: {result.get('error', 'unknown')}")
                    return False, metrics
            else:
                # No reservation - direct queue
                result = await audio_router.play_audio(
                    audio_data=pcm_data,
                    sample_rate=decoded_sample_rate,
                    priority="normal",
                    blocking=blocking,
                )
                if result.get("queued"):
                    metrics.chunks_played = metrics.chunks_received
                    logger.info(f"Audio queued for playback, position: {result.get('position', 0)}")
                else:
                    logger.error(f"Failed to queue audio: {result.get('error', 'unknown')}")
                    return False, metrics

        end_time = time.perf_counter()
        metrics.playback_time = end_time - start_time

        # Log TTS playback end with metrics
        if event_logger:
            tts_event_data = {
                "metrics": {
                    "ttfa_ms": round(metrics.ttfa * 1000, 1),
                    "total_time_ms": round(metrics.playback_time * 1000, 1),
                    "bytes_received": bytes_received,
                    "chunks": metrics.chunks_received,
                    "format": format,
                    "sample_rate_hz": decoded_sample_rate
                }
            }
            event_logger.log_event(event_logger.TTS_PLAYBACK_END, tts_event_data)

        logger.info(f"Streaming complete - TTFA: {metrics.ttfa:.3f}s, "
                   f"Total: {metrics.playback_time:.3f}s")

        # Save audio if enabled
        if save_audio and audio_dir:
            try:
                from .core import save_debug_file
                audio_buffer.seek(0)
                audio_data = audio_buffer.read()
                audio_path = save_debug_file(audio_data, "tts", format, audio_dir, True, conversation_id)
                if audio_path:
                    logger.info(f"TTS audio saved to: {audio_path}")
                    metrics.audio_path = audio_path
            except Exception as e:
                logger.error(f"Failed to save TTS audio: {e}")

        return True, metrics

    except Exception as e:
        logger.error(f"Buffered streaming failed: {e}")
        return False, metrics