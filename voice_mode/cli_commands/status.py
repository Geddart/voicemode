"""Unified status command for VoiceMode.

Shows complete state of VoiceMode - how it's running, which services are available,
and their configuration in a single view.

Note: This is a TTS-only version (Whisper STT has been removed).
"""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import click

from voice_mode.config import (
    KOKORO_PORT,
    TTS_VOICES,
    OPENAI_API_KEY,
    env_bool,
)
from voice_mode.utils.services.common import find_process_by_port, check_service_status


class ServiceStatus(str, Enum):
    """Status of a service."""
    RUNNING = "running"
    NOT_RUNNING = "not_running"
    NOT_INSTALLED = "not_installed"
    FORWARDED = "forwarded"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Information about a service."""
    name: str
    type: str  # "tts"
    status: ServiceStatus
    port: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    auto_start: bool = False
    health: Optional[str] = None


@dataclass
class DependencyInfo:
    """Information about a dependency."""
    name: str
    installed: bool
    version: Optional[str] = None
    path: Optional[str] = None


@dataclass
class StatusData:
    """Complete status data structure."""
    version: str
    runtime: Dict[str, str]
    tts: Dict[str, Any]
    config: Dict[str, Any]
    dependencies: Dict[str, bool]


def check_ffmpeg() -> DependencyInfo:
    """Check if ffmpeg is installed."""
    path = shutil.which("ffmpeg")
    if not path:
        return DependencyInfo(name="ffmpeg", installed=False)

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        # Extract version from first line
        version = None
        if result.returncode == 0:
            first_line = result.stdout.split("\n")[0]
            if "version" in first_line.lower():
                parts = first_line.split()
                for i, part in enumerate(parts):
                    if part.lower() == "version" and i + 1 < len(parts):
                        version = parts[i + 1]
                        break
        return DependencyInfo(name="ffmpeg", installed=True, version=version, path=path)
    except Exception:
        return DependencyInfo(name="ffmpeg", installed=True, path=path)


def check_portaudio() -> DependencyInfo:
    """Check if PortAudio is installed."""
    # On macOS, check for brew installation
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["brew", "list", "portaudio"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return DependencyInfo(name="portaudio", installed=True)
        return DependencyInfo(name="portaudio", installed=False)

    # On Linux, check for the library
    lib_paths = [
        "/usr/lib/libportaudio.so",
        "/usr/lib/x86_64-linux-gnu/libportaudio.so",
        "/usr/lib/aarch64-linux-gnu/libportaudio.so",
    ]
    for path in lib_paths:
        if Path(path).exists():
            return DependencyInfo(name="portaudio", installed=True, path=path)

    # Try pkg-config
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "portaudio-2.0"],
            capture_output=True
        )
        if result.returncode == 0:
            return DependencyInfo(name="portaudio", installed=True)
    except Exception:
        pass

    return DependencyInfo(name="portaudio", installed=False)


def check_uv() -> DependencyInfo:
    """Check if UV is installed."""
    path = shutil.which("uv")
    if not path:
        return DependencyInfo(name="uv", installed=False)

    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        version = None
        if result.returncode == 0:
            # Output format: "uv 0.x.x"
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                version = parts[1]
        return DependencyInfo(name="uv", installed=True, version=version, path=path)
    except Exception:
        return DependencyInfo(name="uv", installed=True, path=path)


def format_uptime(seconds: float) -> str:
    """Format uptime in a human-readable format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_memory(bytes_val: float) -> str:
    """Format memory in MB."""
    mb = bytes_val / (1024 * 1024)
    if mb >= 1000:
        return f"{mb/1024:.1f} GB"
    return f"{mb:.0f} MB"


def check_kokoro_service() -> ServiceInfo:
    """Check Kokoro (TTS) service status."""
    status, proc = check_service_status(KOKORO_PORT)

    # Check if installed
    voicemode_dir = Path.home() / ".voicemode"
    kokoro_dir = voicemode_dir / "services" / "kokoro"
    is_installed = kokoro_dir.exists() and any(kokoro_dir.iterdir())

    # Check auto-start configuration
    auto_start = False
    if platform.system() == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.voicemode.kokoro.plist"
        auto_start = plist_path.exists()
    else:
        service_path = Path.home() / ".config" / "systemd" / "user" / "voicemode-kokoro.service"
        auto_start = service_path.exists()

    if not is_installed:
        return ServiceInfo(
            name="Kokoro",
            type="tts",
            status=ServiceStatus.NOT_INSTALLED,
            port=KOKORO_PORT,
            auto_start=auto_start
        )

    if status == "local":
        details = {"voice": TTS_VOICES[0] if TTS_VOICES else "af_sky"}

        try:
            # Get memory and uptime
            with proc.oneshot():
                memory_info = proc.memory_info()
                details["memory"] = format_memory(memory_info.rss)
                create_time = proc.create_time()
                uptime_seconds = time.time() - create_time
                details["uptime"] = format_uptime(uptime_seconds)

            # Try to get version info
            try:
                from voice_mode.utils.services.version_info import get_kokoro_version
                version_info = get_kokoro_version()
                if version_info.get("api_version"):
                    details["version"] = version_info["api_version"]
                elif version_info.get("version"):
                    details["version"] = version_info["version"]
            except Exception:
                pass
        except Exception:
            pass

        return ServiceInfo(
            name="Kokoro",
            type="tts",
            status=ServiceStatus.RUNNING,
            port=KOKORO_PORT,
            details=details,
            auto_start=auto_start,
            health="healthy"
        )
    elif status == "forwarded":
        return ServiceInfo(
            name="Kokoro",
            type="tts",
            status=ServiceStatus.FORWARDED,
            port=KOKORO_PORT,
            auto_start=auto_start,
            health="healthy"
        )
    else:
        return ServiceInfo(
            name="Kokoro",
            type="tts",
            status=ServiceStatus.NOT_RUNNING,
            port=KOKORO_PORT,
            auto_start=auto_start
        )


def check_openai_api() -> Dict[str, Any]:
    """Check OpenAI API availability."""
    api_key_set = bool(OPENAI_API_KEY)
    return {
        "status": "available" if api_key_set else "not_configured",
        "api_key_set": api_key_set,
        "tts_model": "tts-1-hd"
    }


def get_active_tts_provider(kokoro: ServiceInfo, openai: Dict[str, Any]) -> str:
    """Determine active TTS provider."""
    if kokoro.status == ServiceStatus.RUNNING or kokoro.status == ServiceStatus.FORWARDED:
        return "kokoro"
    elif openai["status"] == "available":
        return "openai"
    return "none"


def get_config_info() -> Dict[str, Any]:
    """Get configuration information."""
    config_file = Path.home() / ".voicemode" / "voicemode.env"

    voices = TTS_VOICES if TTS_VOICES else ["af_sky"]
    audio_feedback = env_bool("VOICEMODE_AUDIO_FEEDBACK", True)

    return {
        "file": str(config_file) if config_file.exists() else None,
        "voices": voices[:3],  # Show first 3 voices
        "audio_feedback": audio_feedback
    }


def collect_status_data() -> Dict[str, Any]:
    """Collect all status information."""
    from voice_mode.version import __version__

    # Check services
    kokoro = check_kokoro_service()
    openai = check_openai_api()

    # Get active TTS provider
    tts_active = get_active_tts_provider(kokoro, openai)

    # Check dependencies
    ffmpeg = check_ffmpeg()
    portaudio = check_portaudio()
    uv = check_uv()

    # Get config
    config = get_config_info()

    return {
        "version": __version__,
        "runtime": {
            "mode": "mcp",
            "command": "uvx voice-mode"
        },
        "tts": {
            "active": tts_active,
            "providers": {
                "kokoro": {
                    "status": kokoro.status.value,
                    "port": kokoro.port,
                    "voice": kokoro.details.get("voice") if kokoro.details else None,
                    "version": kokoro.details.get("version") if kokoro.details else None,
                    "memory": kokoro.details.get("memory") if kokoro.details else None,
                    "uptime": kokoro.details.get("uptime") if kokoro.details else None,
                    "auto_start": kokoro.auto_start,
                    "health": kokoro.health
                },
                "openai": {
                    "status": openai["status"],
                    "api_key_set": openai["api_key_set"],
                    "model": openai["tts_model"]
                }
            }
        },
        "config": config,
        "dependencies": {
            "ffmpeg": ffmpeg.installed,
            "portaudio": portaudio.installed,
            "uv": uv.installed
        },
        "_raw": {
            "ffmpeg": asdict(ffmpeg),
            "portaudio": asdict(portaudio),
            "uv": asdict(uv)
        }
    }


def format_terminal_output(data: Dict[str, Any], use_colors: bool = True) -> str:
    """Format status data for terminal display."""
    lines = []

    # Header
    lines.append(f"VoiceMode Status (v{data['version']})")
    lines.append("=" * 25)
    lines.append("")
    lines.append(f"Runtime: MCP Server (via {data['runtime']['command']})")
    lines.append("")

    # Helper for status indicators
    def status_symbol(status: str, health: Optional[str] = None) -> str:
        if status == "running":
            return click.style("✓", fg="green") if use_colors else "✓"
        elif status == "forwarded":
            return click.style("↔", fg="cyan") if use_colors else "↔"
        elif status == "available":
            return click.style("✓", fg="green") if use_colors else "✓"
        elif status == "not_running":
            return click.style("✗", fg="red") if use_colors else "✗"
        elif status == "not_installed":
            return click.style("-", fg="bright_black") if use_colors else "-"
        elif status == "not_configured":
            return click.style("-", fg="bright_black") if use_colors else "-"
        return "?"

    def format_status_text(status: str) -> str:
        if status == "running":
            return "Running"
        elif status == "forwarded":
            return "Forwarded"
        elif status == "available":
            return "Available"
        elif status == "not_running":
            return "Not running"
        elif status == "not_installed":
            return "Not installed"
        elif status == "not_configured":
            return "Not configured"
        return status.replace("_", " ").title()

    # Kokoro (TTS)
    kokoro = data["tts"]["providers"]["kokoro"]
    lines.append("── Kokoro (TTS) " + "─" * 29)
    sym = status_symbol(kokoro["status"])
    lines.append(f"  Status:     {sym} {format_status_text(kokoro['status'])}" + (f" (port {kokoro['port']})" if kokoro["status"] == "running" else ""))
    if kokoro.get("voice"):
        lines.append(f"  Voice:      {kokoro['voice']}")
    if kokoro.get("version"):
        lines.append(f"  Version:    {kokoro['version']}")
    if kokoro.get("memory") and kokoro.get("uptime"):
        lines.append(f"  Resources:  {kokoro['memory']}, up {kokoro['uptime']}")
    lines.append(f"  Auto-start: {'enabled' if kokoro.get('auto_start') else 'disabled'}")
    lines.append("")

    # OpenAI API
    openai = data["tts"]["providers"]["openai"]
    lines.append("── OpenAI API " + "─" * 31)
    sym = status_symbol(openai["status"])
    status_text = "Available (API key set)" if openai["api_key_set"] else "Not configured"
    lines.append(f"  Status:     {sym} {status_text}")
    if openai["api_key_set"]:
        lines.append(f"  TTS Model:  {openai['model']}")
    lines.append("")

    # Active Provider
    lines.append("── Active Provider " + "─" * 26)
    tts_active = data["tts"]["active"]

    tts_text = tts_active.title() if tts_active != "none" else "None available"

    if tts_active == "kokoro":
        tts_text += " (local preferred)"

    lines.append(f"  TTS: {tts_text}")
    lines.append("")

    # Dependencies
    lines.append("── Dependencies " + "─" * 29)
    deps = data["dependencies"]
    for name, installed in deps.items():
        sym = status_symbol("running" if installed else "not_running")
        status_text = "Installed" if installed else "Not found"
        lines.append(f"  {name.upper():10} {sym} {status_text}")
    lines.append("")

    # Configuration
    lines.append("── Configuration " + "─" * 28)
    config = data["config"]
    if config.get("file"):
        lines.append(f"  Config: {config['file']}")
    else:
        lines.append("  Config: ~/.voicemode/voicemode.env (not found)")
    lines.append(f"  Voices: {', '.join(config.get('voices', ['af_sky']))}")
    lines.append(f"  Audio feedback: {'enabled' if config.get('audio_feedback') else 'disabled'}")

    return "\n".join(lines)


def format_markdown_output(data: Dict[str, Any]) -> str:
    """Format status data as markdown."""
    lines = []

    lines.append("# VoiceMode Status")
    lines.append("")
    lines.append("## Runtime")
    lines.append(f"- Mode: MCP Server (via {data['runtime']['command']})")
    lines.append(f"- Version: {data['version']}")
    lines.append("")

    lines.append("## Services")
    lines.append("| Service | Type | Status | Details |")
    lines.append("|---------|------|--------|---------|")

    # Kokoro
    kokoro = data["tts"]["providers"]["kokoro"]
    kokoro_details = []
    if kokoro["status"] == "running":
        kokoro_details.append(f"Port {kokoro['port']}")
    if kokoro.get("voice"):
        kokoro_details.append(f"Voice: {kokoro['voice']}")
    lines.append(f"| Kokoro | TTS | {'✓' if kokoro['status'] in ['running', 'forwarded'] else '✗'} {kokoro['status'].replace('_', ' ').title()} | {', '.join(kokoro_details) if kokoro_details else '-'} |")

    # OpenAI TTS
    openai = data["tts"]["providers"]["openai"]
    openai_details = []
    if openai["api_key_set"]:
        openai_details.append("API key set")
        openai_details.append(f"Model: {openai['model']}")
    lines.append(f"| OpenAI | TTS | {'✓' if openai['status'] == 'available' else '✗'} {openai['status'].replace('_', ' ').title()} | {', '.join(openai_details) if openai_details else '-'} |")

    lines.append("")
    lines.append(f"Active TTS: {data['tts']['active'].title()}" +
                 (" (local preferred)" if data['tts']['active'] == 'kokoro' else ""))
    lines.append("")

    lines.append("## Configuration")
    config = data["config"]
    lines.append(f"- Config file: {config.get('file', '~/.voicemode/voicemode.env')}")
    lines.append(f"- Voices: {', '.join(config.get('voices', ['af_sky']))}")
    lines.append(f"- Audio feedback: {'enabled' if config.get('audio_feedback') else 'disabled'}")
    lines.append("")

    lines.append("## Dependencies")
    lines.append("| Dependency | Status |")
    lines.append("|------------|--------|")
    for name, installed in data["dependencies"].items():
        lines.append(f"| {name.title()} | {'✓ Installed' if installed else '✗ Not found'} |")

    return "\n".join(lines)


def format_json_output(data: Dict[str, Any]) -> str:
    """Format status data as JSON."""
    # Remove internal raw data for cleaner output
    output = {k: v for k, v in data.items() if not k.startswith("_")}
    return json.dumps(output, indent=2)


@click.command()
@click.help_option('-h', '--help')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['terminal', 'markdown', 'json']),
              default=None,
              help='Output format (default: auto-detect based on TTY)')
@click.option('--no-color', is_flag=True,
              help='Disable colored output')
def status(output_format: Optional[str], no_color: bool):
    """Show unified VoiceMode status.

    Displays the complete state of VoiceMode including:
    - Service status (Kokoro TTS)
    - OpenAI API availability
    - Active TTS provider
    - System dependencies
    - Configuration

    Examples:
        voicemode status              # Terminal output with colors
        voicemode status --format json   # JSON output for automation
        voicemode status --format markdown  # Markdown for documentation
        voicemode status --no-color   # Plain text without colors
    """
    # Collect status data
    data = collect_status_data()

    # Determine output format
    if output_format is None:
        # Auto-detect: use terminal if interactive, JSON if not
        import sys
        output_format = "terminal" if sys.stdout.isatty() else "json"

    # Check for NO_COLOR environment variable
    use_colors = not no_color and not os.environ.get("NO_COLOR")

    # Format and output
    if output_format == "json":
        click.echo(format_json_output(data))
    elif output_format == "markdown":
        click.echo(format_markdown_output(data))
    else:  # terminal
        click.echo(format_terminal_output(data, use_colors=use_colors))
