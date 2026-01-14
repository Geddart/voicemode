"""Tests for service health check functionality.

Note: This is a TTS-only version (Whisper STT has been removed).
"""

import os
import tempfile
from pathlib import Path
import pytest

from voice_mode.tools.service import load_service_template


def test_systemd_template_simplified():
    """Test that systemd templates are simplified (v1.2.0+).

    Note: As of v1.2.0, templates were simplified to only need START_SCRIPT.
    Health checks were removed in favor of letting start scripts handle config.
    Note: Whisper service has been removed in TTS-only fork.
    """
    from unittest.mock import patch

    # Mock platform to get Linux templates
    with patch('voice_mode.tools.service.platform.system', return_value='Linux'):
        # Test Kokoro systemd template - simplified
        kokoro_template = load_service_template("kokoro")
        assert "{START_SCRIPT}" in kokoro_template
        assert "[Service]" in kokoro_template
        assert "[Unit]" in kokoro_template
        assert "[Install]" in kokoro_template


def test_template_placeholders():
    """Test that templates use consistent placeholders.

    Note: As of v1.2.0, templates were simplified to only need START_SCRIPT.
    Port, directory, and log configs are handled by start scripts via voicemode.env.
    Note: Whisper service has been removed in TTS-only fork.
    """
    from unittest.mock import patch

    # Mock platform to get Linux templates
    with patch('voice_mode.tools.service.platform.system', return_value='Linux'):
        # Kokoro templates - simplified to just START_SCRIPT
        kokoro_systemd = load_service_template("kokoro")
        assert "{START_SCRIPT}" in kokoro_systemd
        # Removed in v1.2.0: KOKORO_PORT, KOKORO_DIR (handled by start script)
