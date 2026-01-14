"""
Tests for the unified service management tool.

Note: This is a TTS-only version (Whisper STT has been removed).
"""
import os
import sys
import platform
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
import pytest
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the service function - get the actual function from the tool decorator
from voice_mode.tools.service import service as service_tool

# Extract the actual function from the FastMCP tool wrapper
service = service_tool.fn

# Import prompts for testing
from voice_mode.prompts.services import kokoro_prompt as kokoro_prompt_tool

# Extract the actual functions from FastMCP prompt wrappers
kokoro_prompt = kokoro_prompt_tool.fn


class TestUnifiedServiceTool:
    """Test cases for the unified service management tool (Kokoro only)"""

    @pytest.mark.asyncio
    async def test_status_service_running(self):
        """Test status when service is running"""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.oneshot.return_value.__enter__.return_value = None
        mock_proc.cpu_percent.return_value = 15.5
        mock_proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)  # 100 MB
        mock_proc.create_time.return_value = 1000000000
        mock_proc.cmdline.return_value = ["uvicorn", "api.src.main:app"]

        with patch('voice_mode.tools.service.check_service_status', return_value=("local", mock_proc)), \
             patch('time.time', return_value=1000001000):  # 1000 seconds later
            result = await service("kokoro", "status")
            assert "✅" in result
            assert "is running" in result
            assert "PID: 12345" in result
            assert "CPU: 15.5%" in result
            assert "Memory: 100.0 MB" in result
            assert "16m 40s" in result  # uptime

    @pytest.mark.asyncio
    async def test_start_service_already_running(self):
        """Test starting a service that's already running"""
        mock_proc = MagicMock()
        with patch('voice_mode.tools.service.find_process_by_port', return_value=mock_proc):
            result = await service("kokoro", "start")
            assert "already running" in result

    @pytest.mark.asyncio
    async def test_stop_service_not_running(self):
        """Test stopping a service that's not running"""
        with patch('voice_mode.tools.service.find_process_by_port', return_value=None), \
             patch('pathlib.Path.exists', return_value=False):
            result = await service("kokoro", "stop")
            assert "not running" in result.lower()

    @pytest.mark.asyncio
    async def test_stop_service_success(self):
        """Test successfully stopping a service"""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()

        # Mock platform and service files to force fallback to process termination
        with patch('voice_mode.tools.service.find_process_by_port', return_value=mock_proc), \
             patch('platform.system', return_value='Darwin'), \
             patch('pathlib.Path.exists', return_value=False):  # No service files exist
            result = await service("kokoro", "stop")
            assert "✅" in result
            assert "stopped" in result
            assert "was PID: 12345" in result
            mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_service_linux(self):
        """Test enabling service on Linux"""
        # Template with proper placeholders (v1.2.0+ uses START_SCRIPT)
        mock_template_content = "[Service]\nExecStart={START_SCRIPT}\n"

        with patch('platform.system', return_value='Linux'), \
             patch('voice_mode.tools.service.get_installed_service_version', return_value="1.0.0"), \
             patch('voice_mode.tools.service.load_service_file_version', return_value="1.0.0"), \
             patch('voice_mode.tools.service.load_service_template', return_value=mock_template_content), \
             patch('voice_mode.tools.service.find_kokoro_fastapi', return_value="/path/to/kokoro"), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.write_text'), \
             patch('subprocess.run') as mock_run:

            mock_run.return_value = MagicMock(returncode=0)

            result = await service("kokoro", "enable")
            assert "✅" in result
            assert "enabled and started" in result

            # Verify systemctl commands were called
            assert any("daemon-reload" in str(call) for call in mock_run.call_args_list)
            assert any("enable" in str(call) for call in mock_run.call_args_list)
            assert any("start" in str(call) for call in mock_run.call_args_list)

    @pytest.mark.asyncio
    async def test_disable_service_not_installed(self):
        """Test disabling service that's not installed"""
        with patch('platform.system', return_value='Darwin'), \
             patch('pathlib.Path.exists', return_value=False):

            result = await service("kokoro", "disable")
            assert "not installed" in result

    @pytest.mark.asyncio
    async def test_view_logs_linux(self):
        """Test viewing logs on Linux"""
        with patch('platform.system', return_value='Linux'), \
             patch('subprocess.run') as mock_run:

            journal_output = "Jan 15 10:00:00 systemd[1]: Started voicemode-kokoro.service"
            mock_run.return_value = MagicMock(returncode=0, stdout=journal_output)

            result = await service("kokoro", "logs", lines=20)
            assert "Last 20 journal entries" in result
            assert "Started voicemode-kokoro.service" in result

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        """Test invalid action handling"""
        result = await service("kokoro", "invalid_action")  # type: ignore
        assert "❌" in result
        assert "Unknown action" in result

    @pytest.mark.skip(reason="Whisper service removed in TTS-only fork")
    @pytest.mark.asyncio
    async def test_invalid_service_name(self):
        """Test that invalid service names are rejected"""
        pass


class TestServicePrompts:
    """Test service-specific prompts"""

    def test_kokoro_prompt_valid_action(self):
        """Test kokoro prompt with valid action"""
        result = kokoro_prompt("start")
        assert "service tool" in result
        assert "service_name='kokoro'" in result
        assert "action='start'" in result

    def test_kokoro_prompt_invalid_action(self):
        """Test kokoro prompt with invalid action"""
        result = kokoro_prompt("invalid")
        assert "Invalid action" in result
        assert "Use one of:" in result

    def test_kokoro_prompt_install_action(self):
        """Test kokoro prompt with install action"""
        result = kokoro_prompt("install")
        assert "kokoro_install" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
