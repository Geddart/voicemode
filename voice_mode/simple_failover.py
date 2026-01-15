"""
Simple failover implementation for voice-mode.

This module provides a direct try-and-failover approach without health checks.
Connection refused errors are instant, so there's no performance penalty.
"""

import logging
from typing import Optional, Tuple, Dict, Any
from openai import AsyncOpenAI
from .openai_error_parser import OpenAIErrorParser
from .provider_discovery import is_local_provider

from .config import TTS_BASE_URLS, OPENAI_API_KEY
from .provider_discovery import detect_provider_type

logger = logging.getLogger("voicemode")


async def simple_tts_failover(
    text: str,
    voice: str,
    model: str,
    background: bool = False,
    **kwargs
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Simple TTS failover - try each endpoint in order until one works.
    
    Returns:
        Tuple of (success, metrics, config)
    """
    logger.info(f"simple_tts_failover called with: text='{text[:50]}...', voice={voice}, model={model}")
    logger.info(f"kwargs: {kwargs}")
    
    from .core import text_to_speech
    from .conversation_logger import get_conversation_logger

    # Track attempted endpoints and their errors
    attempted_endpoints = []

    # Get conversation ID from logger
    conversation_logger = get_conversation_logger()
    conversation_id = conversation_logger.conversation_id

    # Try each TTS endpoint in order
    logger.info(f"simple_tts_failover: Starting with TTS_BASE_URLS = {TTS_BASE_URLS}")
    for base_url in TTS_BASE_URLS:
        logger.info(f"Trying TTS endpoint: {base_url}")

        # Create client for this endpoint
        provider_type = detect_provider_type(base_url)
        api_key = OPENAI_API_KEY if provider_type == "openai" else (OPENAI_API_KEY or "dummy-key-for-local")

        # Select appropriate voice for this provider
        if provider_type == "openai":
            # Map Kokoro voices to OpenAI equivalents, or use OpenAI default
            openai_voices = ["alloy", "echo", "fable", "nova", "onyx", "shimmer"]
            if voice in openai_voices:
                selected_voice = voice
            else:
                # Map common Kokoro voices to OpenAI equivalents
                voice_mapping = {
                    "af_sky": "nova",
                    "af_sarah": "nova",
                    "af_alloy": "alloy",
                    "am_adam": "onyx",
                    "am_echo": "echo",
                    "am_onyx": "onyx",
                    "bm_fable": "fable"
                }
                selected_voice = voice_mapping.get(voice, "alloy")  # Default to alloy
                logger.info(f"Mapped voice {voice} to {selected_voice} for OpenAI")
        else:
            selected_voice = voice  # Use original voice for Kokoro

        # Disable retries for local endpoints - they either work or don't
        max_retries = 0 if is_local_provider(base_url) else 2
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30.0,  # Reasonable timeout
            max_retries=max_retries
        )

        # Create clients dict for text_to_speech
        openai_clients = {'tts': client}

        # Try TTS with this endpoint
        # Wrap in try/catch to get actual exception details
        last_exception = None
        try:
            success, metrics = await text_to_speech(
                text=text,
                openai_clients=openai_clients,
                tts_model=model,
                tts_voice=selected_voice,
                tts_base_url=base_url,
                conversation_id=conversation_id,
                background=background,
                **kwargs
            )

            if success:
                config = {
                    'base_url': base_url,
                    'provider': provider_type,
                    'voice': selected_voice,  # Return the voice actually used
                    'model': model,
                    'endpoint': f"{base_url}/audio/speech"
                }
                logger.info(f"TTS succeeded with {base_url} using voice {selected_voice}")
                return True, metrics, config
            else:
                # text_to_speech returned False, but we don't have exception details
                # Create a generic error message
                last_exception = Exception("TTS request failed")

        except Exception as e:
            last_exception = e

        # Handle the error (either from exception or False return)
        if last_exception:
            error_message = str(last_exception)
            logger.error(f"TTS failed for {base_url}: {error_message}")
            logger.debug(f"Exception type: {type(last_exception).__name__}")  # Debug logging

            # Parse OpenAI errors for better user feedback
            error_details = None
            if provider_type == "openai":
                error_details = OpenAIErrorParser.parse_error(last_exception, endpoint=f"{base_url}/audio/speech")
                # Log the user-friendly error message
                if error_details and error_details.get('title'):
                    logger.error(f"  {error_details['title']}: {error_details.get('message', '')}")
                    if error_details.get('suggestion'):
                        logger.info(f"  💡 {error_details['suggestion']}")

            # Add to attempted endpoints with error details
            attempted_endpoints.append({
                'endpoint': f"{base_url}/audio/speech",
                'provider': provider_type,
                'voice': selected_voice,
                'model': model,
                'error': error_message,
                'error_details': error_details  # Include parsed error details
            })

            # Continue to next endpoint
            continue

    # All endpoints failed - return detailed error info
    logger.error(f"All TTS endpoints failed after {len(attempted_endpoints)} attempts")
    error_config = {
        'error_type': 'all_providers_failed',
        'attempted_endpoints': attempted_endpoints
    }
    return False, None, error_config