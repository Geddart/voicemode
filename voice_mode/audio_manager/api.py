"""
HTTP API routes for the Audio Manager service.

Provides REST endpoints for:
- POST /speak - Queue audio for playback
- POST /wait/{item_id} - Wait for specific audio to finish
- GET /status - Get current status
- POST /pause - Pause playback
- POST /resume - Resume playback
- POST /clear - Clear queue
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


async def speak(request: Request) -> JSONResponse:
    """Queue audio for playback."""
    if not _service:
        return JSONResponse({"error": "Service not initialized"}, status_code=500)

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

    # Extract parameters
    audio_data_b64 = body.get("audio_data")
    if not audio_data_b64:
        return JSONResponse({"error": "Missing audio_data"}, status_code=400)

    try:
        audio_data = base64.b64decode(audio_data_b64)
    except Exception as e:
        return JSONResponse({"error": f"Invalid base64 audio_data: {e}"}, status_code=400)

    sample_rate = body.get("sample_rate", 24000)
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

    # Queue the audio
    result = _service.queue_audio(
        audio_data=audio_data,
        sample_rate=sample_rate,
        project=project,
        priority=priority_enum,
    )

    logger.info(f"Queued audio from {project}, position: {result.get('position')}")
    return JSONResponse(result)


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
        Route("/speak", speak, methods=["POST"]),
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
