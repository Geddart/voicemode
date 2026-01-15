"""Provider management tools for voice-mode (TTS only)."""

import logging
from typing import Optional, Union

from voice_mode.server import mcp
from voice_mode.provider_discovery import provider_registry, detect_provider_type, EndpointInfo
from voice_mode.config import TTS_BASE_URLS
from datetime import datetime, timezone

logger = logging.getLogger("voicemode")


@mcp.tool()
async def refresh_provider_registry(
    base_url: Optional[str] = None,
    optimistic: Union[bool, str] = True
) -> str:
    """Manually refresh health checks for TTS provider endpoints.

    Useful when a service has been started/stopped and you want to update
    the registry without restarting the MCP server.

    Args:
        base_url: Optional - specific endpoint URL to refresh
        optimistic: If True, mark all endpoints as healthy without checking (default: True)

    Returns:
        Summary of refreshed endpoints and their status
    """
    try:
        results = ["🔄 Provider Registry Refresh"]
        results.append("=" * 50)

        results.append("\nTTS Endpoints:")
        results.append("-" * 30)

        urls = list(TTS_BASE_URLS)

        # If specific URL requested, only check that one
        if base_url:
            if base_url not in urls:
                results.append(f"  ⚠️  {base_url} not in configured URLs")
                return "\n".join(results)
            urls = [base_url]

        for url in urls:
            if optimistic:
                # In optimistic mode, just mark everything as available
                provider_registry.registry["tts"][url] = EndpointInfo(
                    base_url=url,
                    models=["tts-1", "tts-1-hd"] if "openai.com" in url else ["tts-1"],
                    voices=["alloy", "echo", "fable", "nova", "onyx", "shimmer"] if "openai.com" in url else ["af_alloy", "af_aoede", "af_bella", "af_heart", "af_jadzia", "af_jessica", "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "af_v0", "af_v0bella", "af_v0irulan", "af_v0nicole", "af_v0sarah", "af_v0sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa", "am_v0adam", "am_v0gurney", "am_v0michael", "bf_alice", "bf_emma", "bf_lily", "bf_v0emma", "bf_v0isabella", "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "bm_v0george", "bm_v0lewis", "ef_dora", "em_alex", "em_santa", "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi", "if_sara", "im_nicola", "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa", "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"],
                    provider_type=detect_provider_type(url),
                    last_check=datetime.now(timezone.utc).isoformat()
                )
                results.append(f"\n  ✅ {url}")
                results.append(f"     Status: Available (optimistic mode)")
            else:
                # Non-optimistic mode: Actually discover endpoint capabilities
                try:
                    await provider_registry._discover_endpoint(url)
                    endpoint_info = provider_registry.registry["tts"][url]

                    if endpoint_info.last_error:
                        results.append(f"\n  ❌ {url}")
                        results.append(f"     Error: {endpoint_info.last_error}")
                    else:
                        results.append(f"\n  ✅ {url}")
                        if endpoint_info.models:
                            results.append(f"     Models: {', '.join(endpoint_info.models)}")
                        if endpoint_info.voices:
                            results.append(f"     Voices: {', '.join(endpoint_info.voices[:5])}{'...' if len(endpoint_info.voices) > 5 else ''}")
                except Exception as e:
                    results.append(f"\n  ❌ {url}")
                    results.append(f"     Error: {str(e)}")

        results.append("\n✨ Refresh complete!")
        return "\n".join(results)

    except Exception as e:
        logger.error(f"Error refreshing provider registry: {e}")
        return f"Error refreshing provider registry: {str(e)}"


@mcp.tool()
async def get_provider_details(base_url: str) -> str:
    """Get detailed information about a specific TTS provider endpoint.

    Args:
        base_url: The base URL of the provider (e.g., 'http://127.0.0.1:8880/v1')

    Returns:
        Detailed information about the provider including all models and voices
    """
    try:
        # Ensure registry is initialized
        await provider_registry.initialize()

        # Check TTS registry
        if base_url not in provider_registry.registry["tts"]:
            return f"Error: Endpoint '{base_url}' not found in TTS registry"

        endpoint_info = provider_registry.registry["tts"][base_url]

        results = [f"📊 Provider Details: {base_url}"]
        results.append("=" * 50)

        results.append(f"\nService Type: TTS")
        results.append(f"Provider Type: {endpoint_info.provider_type or 'unknown'}")
        results.append(f"Last Check: {endpoint_info.last_check or 'Never'}")

        if endpoint_info.last_error:
            results.append(f"\n⚠️  Error: {endpoint_info.last_error}")
        else:
            results.append(f"Status: ✅ Available")

        if endpoint_info.models:
            results.append(f"\n📦 Models ({len(endpoint_info.models)}):")
            for model in endpoint_info.models:
                results.append(f"  • {model}")
        else:
            results.append("\n📦 Models: None detected")

        if endpoint_info.voices:
            results.append(f"\n🔊 Voices ({len(endpoint_info.voices)}):")
            for voice in endpoint_info.voices:
                results.append(f"  • {voice}")

        return "\n".join(results)

    except Exception as e:
        logger.error(f"Error getting provider details: {e}")
        return f"Error getting provider details: {str(e)}"
