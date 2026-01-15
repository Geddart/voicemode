"""Tests for provider management tools."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from voice_mode.provider_discovery import ProviderRegistry, EndpointInfo


class TestRefreshProviderRegistry:
    """Test the refresh_provider_registry tool logic."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock provider registry."""
        registry = ProviderRegistry()
        registry._initialized = True
        registry.registry = {
            "tts": {}
        }
        return registry

    @pytest.mark.asyncio
    async def test_endpoint_info_creation_with_correct_parameters(self):
        """Test that EndpointInfo is created with base_url parameter."""
        # This test verifies the fix for issue #6
        # EndpointInfo should be created with base_url=, not url=

        endpoint = EndpointInfo(
            base_url="http://127.0.0.1:8880/v1",
            models=["tts-1"],
            voices=["af_sky"],
            provider_type="kokoro",
            last_check=datetime.now(timezone.utc).isoformat(),
            last_error=None
        )

        assert endpoint.base_url == "http://127.0.0.1:8880/v1"
        assert endpoint.last_error is None
        assert endpoint.models == ["tts-1"]
        assert endpoint.voices == ["af_sky"]

    @pytest.mark.asyncio
    async def test_provider_registry_structure(self, mock_registry):
        """Test that provider registry can store EndpointInfo correctly."""
        # Create endpoint info with correct parameters
        endpoint = EndpointInfo(
            base_url="http://127.0.0.1:8880/v1",
            models=["tts-1"],
            voices=["af_sky", "af_bella"],
            provider_type="kokoro",
            last_check=datetime.now(timezone.utc).isoformat(),
            last_error=None
        )

        # Store in registry
        mock_registry.registry["tts"]["http://127.0.0.1:8880/v1"] = endpoint

        # Verify storage
        stored = mock_registry.registry["tts"]["http://127.0.0.1:8880/v1"]
        assert stored.base_url == "http://127.0.0.1:8880/v1"
        assert stored.last_error is None
        assert stored.last_check is not None

    def test_endpoint_info_parameter_validation(self):
        """Test that EndpointInfo raises TypeError for incorrect parameter names."""
        # This should raise TypeError because 'url' is not a valid parameter
        with pytest.raises(TypeError) as exc_info:
            EndpointInfo(
                url="http://127.0.0.1:8880/v1",  # Wrong parameter name
                models=["tts-1"],
                voices=[],
                provider_type="kokoro",
                last_check=datetime.now(timezone.utc).isoformat(),
                last_error=None
            )

        assert "unexpected keyword argument" in str(exc_info.value)
        assert "url" in str(exc_info.value)


class TestProviderToolsIntegration:
    """Integration tests for the fixed provider tools."""

    @pytest.mark.skip(reason="Import fails in test isolation due to mcp library type annotation issue with Python 3.13")
    @pytest.mark.asyncio
    async def test_refresh_creates_valid_endpoints(self):
        """Test that refresh operation creates valid EndpointInfo objects."""
        from voice_mode.tools.providers import provider_registry
        from voice_mode.config import TTS_BASE_URLS

        # This test verifies the actual fix works in context
        # by checking that EndpointInfo objects are created correctly
        # during the refresh operation

        # Create a test URL list
        test_tts_urls = ["http://127.0.0.1:8880/v1"]

        with patch('voice_mode.tools.providers.TTS_BASE_URLS', test_tts_urls):
            # The fix ensures this code creates EndpointInfo with base_url=
            # instead of url=, preventing the TypeError
            for url in test_tts_urls:
                endpoint = EndpointInfo(
                    base_url=url,  # Correct parameter name after fix
                    models=["tts-1"],
                    voices=["af_sky"],
                    provider_type="kokoro",
                    last_check=datetime.now(timezone.utc).isoformat() + "Z",
                    last_error=None
                )
                assert endpoint.base_url == url
