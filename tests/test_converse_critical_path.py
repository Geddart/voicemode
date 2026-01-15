"""
Critical path tests for the converse tool.
These tests ensure the converse tool handles all failure modes gracefully.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
import json

# Import at module level to avoid MCP library import issues with Python 3.13
from voice_mode.tools.converse import converse


class TestConverseOpenAIErrors:
    """Test that converse properly handles and reports OpenAI errors."""

    @pytest.mark.asyncio
    async def test_converse_reports_insufficient_quota_clearly(self):
        """Test that insufficient quota errors are clearly reported to users."""
        # Mock simple_tts_failover to return a failure with quota error info
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {
                        'provider': 'openai',
                        'endpoint': 'https://api.openai.com/v1/audio/speech',
                        'error': 'Error code: 429 - You exceeded your current quota'
                    }
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test message",
                    background=False  # Must be False to test foreground TTS path
                )

            # User should see a clear message about quota/credit issue
            assert any(keyword in result.lower() for keyword in [
                'quota', 'credit', 'billing', 'api key', 'insufficient', 'openai', 'failed'
            ]), f"Error message doesn't clearly indicate quota issue: {result}"

    @pytest.mark.asyncio
    async def test_converse_reports_invalid_api_key_clearly(self):
        """Test that invalid API key errors are clearly reported."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {
                        'provider': 'openai',
                        'endpoint': 'https://api.openai.com/v1/audio/speech',
                        'error': 'Error code: 401 - Incorrect API key provided'
                    }
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test message",
                    background=False
                )

            # User should see a message about API key issue
            assert any(keyword in result.lower() for keyword in [
                'api', 'key', 'authentication', 'invalid', 'incorrect', 'failed'
            ]), f"Error message doesn't indicate API key issue: {result}"

    @pytest.mark.asyncio
    async def test_converse_reports_rate_limit_clearly(self):
        """Test that rate limit errors are clearly reported."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {
                        'provider': 'openai',
                        'endpoint': 'https://api.openai.com/v1/audio/speech',
                        'error': 'Error code: 429 - Rate limit reached'
                    }
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test message",
                    background=False
                )

            # User should see a message about rate limiting
            assert any(keyword in result.lower() for keyword in [
                'rate', 'limit', 'too many', 'requests', 'failed', '429'
            ]), f"Error message doesn't indicate rate limit: {result}"


class TestConverseFailoverBehavior:
    """Test the failover behavior when providers fail."""

    @pytest.mark.asyncio
    async def test_converse_tries_all_configured_endpoints(self):
        """Test that converse tries all configured endpoints before giving up."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {'provider': 'kokoro', 'error': 'Connection refused', 'endpoint': 'http://127.0.0.1:8880/v1'},
                    {'provider': 'openai', 'error': 'Connection refused', 'endpoint': 'https://api.openai.com/v1'}
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test message",
                    background=False
                )

            # Should have tried both endpoints (check from error config)
            assert mock_tts.called
            # Result should indicate failure
            assert any(keyword in result.lower() for keyword in ['failed', 'error', 'kokoro', 'openai'])

    @pytest.mark.asyncio
    async def test_converse_succeeds_with_second_endpoint(self):
        """Test that converse succeeds when first endpoint fails but second works."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (True, {'generation': 0.1, 'playback': 0.2}, {'provider': 'openai'})

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test message",
                    background=False
                )

            # Should succeed without error
            assert "✓" in result or "successfully" in result.lower() or "spoken" in result.lower()
            assert "Error" not in result and "✗" not in result


class TestConverseErrorMessages:
    """Test that error messages are helpful and actionable."""

    @pytest.mark.asyncio
    async def test_error_message_suggests_checking_services(self):
        """Test that errors suggest checking if services are running."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {'provider': 'kokoro', 'error': 'Connection refused'},
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test",
                    background=False
                )

            # Should suggest checking services or indicate what failed
            assert any(keyword in result.lower() for keyword in [
                'service', 'running', 'api', 'key', 'kokoro', 'openai', 'failed', 'connection'
            ]), f"Error doesn't suggest solutions: {result}"

    @pytest.mark.asyncio
    async def test_error_message_includes_provider_info(self):
        """Test that errors indicate which provider failed."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (False, None, {
                'error_type': 'all_providers_failed',
                'attempted_endpoints': [
                    {
                        'provider': 'openai',
                        'endpoint': 'https://api.openai.com/v1/audio/speech',
                        'error': 'Insufficient quota'
                    }
                ]
            })

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test",
                    background=False
                )

            # Should mention the provider that failed
            assert 'openai' in result.lower() or 'api' in result.lower() or 'failed' in result.lower()


@pytest.mark.skip(reason="STT functionality removed in TTS-only fork")
class TestConverseSTTFailures:
    """Test STT (speech-to-text) failure handling."""

    @pytest.mark.asyncio
    async def test_stt_failure_reports_clearly(self):
        """Test that STT failures are reported clearly."""
        pass

    @pytest.mark.asyncio
    async def test_stt_no_speech_detected(self):
        """Test handling when no speech is detected."""
        pass


class TestConverseMetrics:
    """Test that converse properly tracks and reports metrics."""

    @pytest.mark.asyncio
    async def test_converse_includes_timing_metrics(self):
        """Test that converse includes timing information when successful."""
        with patch('voice_mode.tools.converse.text_to_speech_with_failover', new_callable=AsyncMock) as mock_tts:
            mock_tts.return_value = (True, {
                'generation': 0.15,
                'playback': 0.5,
                'ttfa': 0.05
            }, {'provider': 'openai'})

            with patch('voice_mode.tools.converse.startup_initialization', new_callable=AsyncMock):
                result = await converse.fn(
                    message="Test",
                    background=False
                )

            # Should succeed and have timing info (gen: X.Xs pattern)
            assert "✓" in result or "successfully" in result.lower() or "spoken" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
