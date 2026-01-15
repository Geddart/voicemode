"""
HTTP API routes for the Audio Manager service.

Provides REST endpoints for:
- POST /speak-text - Generate TTS and queue for playback
- POST /reserve - Reserve a queue slot (for FIFO ordering)
- POST /fill/{item_id} - Fill a reserved slot with audio
- POST /wait/{item_id} - Wait for specific audio to finish
- GET /status - Get current status
- POST /pause - Pause playback
- POST /resume - Resume playback
- POST /clear - Clear queue
- POST /stop - Stop current playback
- POST /chime-allowed - Check if chime is allowed (rate-limiting)
- GET /health - Health check
"""

import base64
import logging
import time
from typing import Optional, TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from .service import AudioManagerService

logger = logging.getLogger("audio_manager.api")

# Reference to the service (set by service.py)
_service: Optional["AudioManagerService"] = None
_start_time: float = 0


def set_service(service: "AudioManagerService"):
    """Set the service reference for API handlers."""
    global _service, _start_time
    _service = service
    _start_time = time.time()


async def health(request: Request) -> JSONResponse:
    """Health check endpoint."""
    uptime = time.time() - _start_time if _start_time else 0
    return JSONResponse({
        "status": "ok",
        "uptime_seconds": int(uptime),
        "version": "0.1.0",
    })


async def status(request: Request) -> JSONResponse:
    """Get current service status."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    return JSONResponse(_service.get_status())


async def pause(request: Request) -> JSONResponse:
    """Pause current playback."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    success = _service.pause()
    return JSONResponse({"paused": success})


async def resume(request: Request) -> JSONResponse:
    """Resume paused playback."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    success = _service.resume()
    return JSONResponse({"paused": not success})


async def clear(request: Request) -> JSONResponse:
    """Clear the audio queue."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    project = None
    try:
        body = await request.json()
        project = body.get("project")
    except Exception:
        pass  # No body or invalid JSON is OK

    cleared = _service.clear_queue(project)
    return JSONResponse({"cleared": cleared})


async def stop(request: Request) -> JSONResponse:
    """Stop current playback."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    success = _service.stop()
    return JSONResponse({"stopped": success})


async def wait_for_item(request: Request) -> JSONResponse:
    """Wait for a specific audio item to finish playing."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    # Get item_id from path
    item_id = request.path_params.get("item_id")
    if not item_id:
        return JSONResponse({"error": "Missing item_id"}, status_code=400)

    # Get timeout from query params (default 120s)
    timeout_str = request.query_params.get("timeout", "120")
    try:
        timeout = float(timeout_str)
    except ValueError:
        timeout = 120.0

    # Wait for the item to complete
    completed = await _service.wait_for_item(item_id, timeout)

    if completed:
        return JSONResponse({"completed": True, "item_id": item_id})
    else:
        return JSONResponse({"completed": False, "item_id": item_id, "error": "timeout"})


async def chime_allowed(request: Request) -> JSONResponse:
    """Check if a chime is allowed (rate-limiting across all windows).

    This endpoint both checks AND records the chime time if allowed.
    Call this before playing a chime - if allowed=True, the chime time
    is recorded and subsequent calls will return allowed=False until cooldown.
    """
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    result = _service.check_chime_allowed()
    return JSONResponse(result)


async def _generate_tts(text: str, voice: str, speed: float) -> tuple[bytes, int]:
    """Generate TTS audio via Kokoro API directly.

    Args:
        text: Text to speak
        voice: Voice name (e.g., 'af_sky')
        speed: Speech rate (0.25-4.0)

    Returns:
        Tuple of (audio_bytes, sample_rate)
    """
    import httpx

    kokoro_url = "http://127.0.0.1:8880/v1/audio/speech"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            kokoro_url,
            json={
                "model": "tts-1",
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": "pcm",
            },
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()

        # PCM audio at 24kHz
        return response.content, 24000


async def speak_text(request: Request) -> JSONResponse:
    """Generate TTS and queue for playback.

    Calls Kokoro TTS directly (no circular HTTP).

    Request body:
        text: str - Text to speak (required)
        voice: str - Voice name (default: af_sky)
        speed: float - Speech rate 0.25-4.0 (default: 1.0)
        project: str - Project identifier (default: external)
        wait: bool - Wait for playback to complete (default: false)
    """
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    voice = body.get("voice", "af_sky")
    speed = body.get("speed", 1.0)
    project = body.get("project", "external")
    wait = body.get("wait", False)

    # Validate speed
    if not isinstance(speed, (int, float)) or speed < 0.25 or speed > 4.0:
        return JSONResponse(
            {"error": "speed must be between 0.25 and 4.0"},
            status_code=400
        )

    try:
        from .queue import Priority

        # Reserve slot BEFORE generating TTS to ensure FIFO ordering
        # This ensures that if a short message and long message arrive together,
        # they play in arrival order, not TTS-generation-completion order
        reservation = _service.reserve_slot(project=project, priority=Priority.NORMAL)
        item_id = reservation.get("item_id")
        position = reservation.get("position", 0)

        if not reservation.get("reserved"):
            return JSONResponse(
                {"error": "Failed to reserve audio slot", "spoken": False},
                status_code=503
            )

        logger.info(f"Reserved slot {item_id} at position {position} for '{text[:30]}...'")

        # Generate TTS (may take variable time based on text length)
        audio_bytes, sample_rate = await _generate_tts(text, voice, speed)

        # Fill the reserved slot with generated audio
        fill_result = _service.fill_slot(
            item_id=item_id,
            audio_data=audio_bytes,
            sample_rate=sample_rate,
        )

        if not fill_result.get("filled"):
            return JSONResponse(
                {"error": f"Failed to fill audio slot: {fill_result.get('error')}", "spoken": False},
                status_code=503
            )

        response_data = {
            "spoken": True,
            "item_id": item_id,
            "position": position,
        }

        # Optionally wait for playback to complete
        if wait:
            completed = await _service.wait_for_item(item_id)
            response_data["completed"] = completed

        return JSONResponse(response_data)

    except Exception as e:
        logger.error(f"speak_text error: {e}")
        return JSONResponse(
            {"error": str(e), "spoken": False},
            status_code=503
        )


async def reserve(request: Request) -> JSONResponse:
    """Reserve a queue slot before generating audio.

    Call this BEFORE starting TTS generation to ensure proper FIFO ordering
    across multiple concurrent requests from different windows.

    Returns an item_id to use when filling the slot with audio.
    """
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

    project = body.get("project", "unknown")
    priority = body.get("priority", "normal")

    # Map priority string to enum
    from .queue import Priority
    priority_map = {
        "high": Priority.HIGH,
        "normal": Priority.NORMAL,
        "low": Priority.LOW,
    }
    priority_enum = priority_map.get(priority.lower(), Priority.NORMAL)

    result = _service.reserve_slot(project=project, priority=priority_enum)
    logger.info(f"Reserved slot for {project}, item_id: {result.get('item_id')}")
    return JSONResponse(result)


async def fill(request: Request) -> JSONResponse:
    """Fill a reserved slot with audio data.

    Call this after TTS generation completes with the item_id from reserve().
    """
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    # Get item_id from path
    item_id = request.path_params.get("item_id")
    if not item_id:
        return JSONResponse({"error": "Missing item_id"}, status_code=400)

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

    audio_data_b64 = body.get("audio_data")
    if not audio_data_b64:
        return JSONResponse({"error": "Missing audio_data"}, status_code=400)

    try:
        audio_data = base64.b64decode(audio_data_b64)
    except Exception as e:
        return JSONResponse({"error": f"Invalid base64 audio_data: {e}"}, status_code=400)

    sample_rate = body.get("sample_rate", 24000)

    result = _service.fill_slot(
        item_id=item_id,
        audio_data=audio_data,
        sample_rate=sample_rate,
    )

    if result.get("filled"):
        logger.info(f"Filled slot {item_id}")
    else:
        logger.warning(f"Failed to fill slot {item_id}: {result.get('error')}")

    return JSONResponse(result)


def create_app() -> Starlette:
    """Create the Starlette ASGI application."""
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/status", status, methods=["GET"]),
        Route("/speak-text", speak_text, methods=["POST"]),
        Route("/reserve", reserve, methods=["POST"]),
        Route("/fill/{item_id}", fill, methods=["POST"]),
        Route("/wait/{item_id}", wait_for_item, methods=["POST"]),
        Route("/pause", pause, methods=["POST"]),
        Route("/resume", resume, methods=["POST"]),
        Route("/clear", clear, methods=["POST"]),
        Route("/stop", stop, methods=["POST"]),
        Route("/chime-allowed", chime_allowed, methods=["POST"]),
    ]

    app = Starlette(routes=routes)
    return app
