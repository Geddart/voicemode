"""
CLI entry points for voice-mode package.
"""
import asyncio
import sys
import os
import warnings
import subprocess
import shutil
import click

# Import version info
try:
    from voice_mode.version import __version__
except ImportError:
    __version__ = "unknown"

# Import configuration constants
from voice_mode.config import (
    DEFAULT_LISTEN_DURATION,
    MIN_RECORDING_DURATION,
)


# Suppress known deprecation warnings for better user experience
# These apply to both CLI commands and MCP server operation
# They can be shown with VOICEMODE_DEBUG=true or --debug flag
if not os.environ.get('VOICEMODE_DEBUG', '').lower() in ('true', '1', 'yes'):
    # Suppress audioop deprecation warning from pydub
    warnings.filterwarnings('ignore', message='.*audioop.*deprecated.*', category=DeprecationWarning)
    # Suppress pkg_resources deprecation warning from webrtcvad
    warnings.filterwarnings('ignore', message='.*pkg_resources.*deprecated.*', category=UserWarning)
    # Suppress psutil connections() deprecation warning
    warnings.filterwarnings('ignore', message='.*connections.*deprecated.*', category=DeprecationWarning)
    
    # Also suppress INFO logging for CLI commands (but not for MCP server)
    import logging
    logging.getLogger("voicemode").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# Service management CLI - runs MCP server by default, subcommands override
@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="VoiceMode")
@click.help_option('-h', '--help', help='Show this message and exit')
@click.option('--debug', is_flag=True, help='Enable debug mode and show all warnings')
@click.option('--tools-enabled', help='Comma-separated list of tools to enable (whitelist)')
@click.option('--tools-disabled', help='Comma-separated list of tools to disable (blacklist)')
@click.pass_context
def voice_mode_main_cli(ctx, debug, tools_enabled, tools_disabled):
    """Voice Mode - MCP server and service management.

    Without arguments, starts the MCP server.
    With subcommands, executes service management operations.
    """
    if debug:
        # Re-enable warnings if debug flag is set
        warnings.resetwarnings()
        os.environ['VOICEMODE_DEBUG'] = 'true'
        # Re-enable INFO logging
        import logging
        logging.getLogger("voicemode").setLevel(logging.INFO)

    # Set environment variables from CLI args
    if tools_enabled:
        os.environ['VOICEMODE_TOOLS_ENABLED'] = tools_enabled
    if tools_disabled:
        os.environ['VOICEMODE_TOOLS_DISABLED'] = tools_disabled

    if ctx.invoked_subcommand is None:
        # No subcommand - run MCP server
        # Note: warnings are already suppressed at module level unless debug is enabled
        from .server import main as voice_mode_main
        voice_mode_main()


def voice_mode() -> None:
    """Entry point for voicemode command - starts the MCP server or runs subcommands."""
    voice_mode_main_cli()


# Service group commands
@voice_mode_main_cli.group()
@click.help_option('-h', '--help', help='Show this message and exit')
def kokoro():
    """Manage Kokoro TTS service."""
    pass


# Service functions are imported lazily in their respective command handlers to improve startup time


# Kokoro service commands
@kokoro.command()
def status():
    """Show Kokoro service status."""
    from voice_mode.tools.service import status_service
    result = asyncio.run(status_service("kokoro"))
    click.echo(result)


@kokoro.command()
def start():
    """Start Kokoro service."""
    from voice_mode.tools.service import start_service
    result = asyncio.run(start_service("kokoro"))
    click.echo(result)


@kokoro.command()
def stop():
    """Stop Kokoro service."""
    from voice_mode.tools.service import stop_service
    result = asyncio.run(stop_service("kokoro"))
    click.echo(result)


@kokoro.command()
def restart():
    """Restart Kokoro service."""
    from voice_mode.tools.service import restart_service
    result = asyncio.run(restart_service("kokoro"))
    click.echo(result)


@kokoro.command()
def enable():
    """Enable Kokoro service to start at boot/login."""
    from voice_mode.tools.service import enable_service
    result = asyncio.run(enable_service("kokoro"))
    click.echo(result)


@kokoro.command()
def disable():
    """Disable Kokoro service from starting at boot/login."""
    from voice_mode.tools.service import disable_service
    result = asyncio.run(disable_service("kokoro"))
    click.echo(result)


@kokoro.command()
@click.help_option('-h', '--help')
@click.option('--lines', '-n', default=50, help='Number of log lines to show')
def logs(lines):
    """View Kokoro service logs."""
    from voice_mode.tools.service import view_logs
    result = asyncio.run(view_logs("kokoro", lines))
    click.echo(result)


@kokoro.command("update-service-files")
def kokoro_update_service_files():
    """Update Kokoro service files to latest version."""
    from voice_mode.tools.service import update_service_files
    result = asyncio.run(update_service_files("kokoro"))
    click.echo(result)


@kokoro.command()
def health():
    """Check Kokoro health endpoint."""
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-s", "http://127.0.0.1:8880/health"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import json
            try:
                health_data = json.loads(result.stdout)
                click.echo("✅ Kokoro is responding")
                click.echo(f"   Status: {health_data.get('status', 'unknown')}")
                if 'uptime' in health_data:
                    click.echo(f"   Uptime: {health_data['uptime']}")
            except json.JSONDecodeError:
                click.echo("✅ Kokoro is responding (non-JSON response)")
        else:
            click.echo("❌ Kokoro not responding on port 8880")
    except subprocess.TimeoutExpired:
        click.echo("❌ Kokoro health check timed out")
    except Exception as e:
        click.echo(f"❌ Health check failed: {e}")


@kokoro.command()
@click.help_option('-h', '--help')
@click.option('--install-dir', help='Directory to install kokoro-fastapi')
@click.option('--port', default=8880, help='Port to configure for the service')
@click.option('--force', '-f', is_flag=True, help='Force reinstall even if already installed')
@click.option('--version', default='latest', help='Version to install (default: latest)')
@click.option('--auto-enable/--no-auto-enable', default=None, help='Enable service at boot/login')
@click.option('--skip-deps', is_flag=True, help='Skip dependency checks (for advanced users)')
def install(install_dir, port, force, version, auto_enable, skip_deps):
    """Install kokoro-fastapi TTS service."""
    from voice_mode.tools.kokoro.install import kokoro_install
    result = asyncio.run(kokoro_install.fn(
        install_dir=install_dir,
        port=port,
        force_reinstall=force,
        version=version,
        auto_enable=auto_enable,
        skip_deps=skip_deps
    ))
    
    if result.get('success'):
        if result.get('already_installed'):
            click.echo(f"✅ Kokoro already installed at {result['install_path']}")
            click.echo(f"   Version: {result.get('version', 'unknown')}")
        else:
            click.echo("✅ Kokoro installed successfully!")
            click.echo(f"   Install path: {result['install_path']}")
            click.echo(f"   Version: {result.get('version', 'unknown')}")
            
        if result.get('enabled'):
            click.echo("   Auto-start: Enabled")
        
        if result.get('migration_message'):
            click.echo(f"\n{result['migration_message']}")
    else:
        click.echo(f"❌ Installation failed: {result.get('error', 'Unknown error')}")
        if result.get('details'):
            click.echo(f"   Details: {result['details']}")


@kokoro.command()
@click.help_option('-h', '--help')
@click.option('--remove-models', is_flag=True, help='Also remove downloaded Kokoro models')
@click.option('--remove-all-data', is_flag=True, help='Remove all Kokoro data including logs and cache')
@click.confirmation_option(prompt='Are you sure you want to uninstall Kokoro?')
def uninstall(remove_models, remove_all_data):
    """Uninstall kokoro-fastapi service and optionally remove data."""
    from voice_mode.tools.kokoro.uninstall import kokoro_uninstall
    result = asyncio.run(kokoro_uninstall.fn(
        remove_models=remove_models,
        remove_all_data=remove_all_data
    ))
    
    if result.get('success'):
        click.echo("✅ Kokoro uninstalled successfully!")
        
        if result.get('service_stopped'):
            click.echo("   Service stopped")
        if result.get('service_disabled'):
            click.echo("   Service disabled")
        if result.get('install_removed'):
            click.echo(f"   Installation removed: {result['install_path']}")
        if result.get('models_removed'):
            click.echo("   Models removed")
        if result.get('data_removed'):
            click.echo("   All data removed")
            
        if result.get('warnings'):
            click.echo("\n⚠️  Warnings:")
            for warning in result['warnings']:
                click.echo(f"   - {warning}")
    else:
        click.echo(f"❌ Uninstall failed: {result.get('error', 'Unknown error')}")
        if result.get('details'):
            click.echo(f"   Details: {result['details']}")


@voice_mode_main_cli.group()
@click.help_option('-h', '--help', help='Show this message and exit')
def config():
    """Manage voicemode configuration."""
    pass


@config.command("list")
def config_list():
    """List all configuration keys with their descriptions."""
    from voice_mode.tools.configuration_management import list_config_keys
    result = asyncio.run(list_config_keys.fn())
    click.echo(result)


@config.command("get")
@click.help_option('-h', '--help')
@click.argument('key')
def config_get(key):
    """Get a configuration value."""
    import os
    from pathlib import Path
    
    # Read from the env file
    env_file = Path.home() / ".voicemode" / "voicemode.env"
    if not env_file.exists():
        click.echo(f"❌ Configuration file not found: {env_file}")
        return
    
    # Look for the key
    found = False
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                if k.strip() == key:
                    click.echo(f"{key}={v.strip()}")
                    found = True
                    break
    
    if not found:
        # Check environment variable
        env_value = os.getenv(key)
        if env_value is not None:
            click.echo(f"{key}={env_value} (from environment)")
        else:
            click.echo(f"❌ Configuration key not found: {key}")
            click.echo("Run 'voicemode config list' to see available keys")


@config.command("set")
@click.help_option('-h', '--help')
@click.argument('key')
@click.argument('value')
def config_set(key, value):
    """Set a configuration value."""
    from voice_mode.tools.configuration_management import update_config
    result = asyncio.run(update_config.fn(key, value))
    click.echo(result)


@config.command("edit")
@click.help_option('-h', '--help')
@click.option('--editor', help='Editor to use (overrides $EDITOR)')
def config_edit(editor):
    """Open the configuration file in your default editor.

    Opens ~/.voicemode/voicemode.env in your configured editor.
    Uses $EDITOR environment variable by default, or you can specify with --editor.

    Examples:
        voicemode config edit           # Use $EDITOR
        voicemode config edit --editor vim
        voicemode config edit --editor "code --wait"
    """
    from pathlib import Path

    # Find the config file
    config_path = Path.home() / ".voicemode" / "voicemode.env"

    # Create default config if it doesn't exist
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        from voice_mode.config import load_voicemode_env
        # This will create the default config
        load_voicemode_env()

    # Determine which editor to use
    if editor:
        editor_cmd = editor
    else:
        # Try environment variables in order of preference
        editor_cmd = (
            os.environ.get('EDITOR') or
            os.environ.get('VISUAL') or
            shutil.which('nano') or
            shutil.which('vim') or
            shutil.which('vi')
        )

    if not editor_cmd:
        click.echo("❌ No editor found. Please set $EDITOR or use --editor")
        click.echo("   Example: export EDITOR=vim")
        click.echo("   Or use: voicemode config edit --editor vim")
        return

    # Handle complex editor commands (e.g., "code --wait")
    if ' ' in editor_cmd:
        import shlex
        cmd_parts = shlex.split(editor_cmd)
        cmd = cmd_parts + [str(config_path)]
    else:
        cmd = [editor_cmd, str(config_path)]

    # Open the editor
    try:
        click.echo(f"Opening {config_path} in {editor_cmd}...")
        subprocess.run(cmd, check=True)
        click.echo("✅ Configuration file edited successfully")
        click.echo("\nChanges will take effect when voicemode is restarted.")
    except subprocess.CalledProcessError:
        click.echo(f"❌ Editor exited with an error")
    except FileNotFoundError:
        click.echo(f"❌ Editor not found: {editor_cmd}")
        click.echo("   Please check that the editor is installed and in your PATH")


# Dependency management group
@voice_mode_main_cli.command()
@click.help_option('-h', '--help')
@click.option('--component', type=click.Choice(['core', 'kokoro']),
              help='Check specific component only')
@click.option('--yes', '-y', is_flag=True, help='Install without prompting')
@click.option('--dry-run', is_flag=True, help='Show what would be installed')
@click.option('--verbose', '-v', is_flag=True, help='Show full installation output')
def deps(component, yes, dry_run, verbose):
    """Check and install system dependencies.

    Shows dependency status and offers to install missing ones.
    Checks core dependencies by default, or specify --component.

    Examples:
        voicemode deps                    # Check all dependencies
        voicemode deps --component kokoro   # Check kokoro dependencies only
        voicemode deps --yes              # Install without prompting
        voicemode deps --verbose          # Show full installation output
    """
    from voice_mode.utils.dependencies.checker import (
        check_component_dependencies,
        load_dependencies,
        install_missing_dependencies
    )

    deps_yaml = load_dependencies()
    components = [component] if component else ['core', 'kokoro']

    all_missing = []

    for comp in components:
        click.echo(f"\n{comp.capitalize()} Dependencies:")
        results = check_component_dependencies(comp, deps_yaml)

        if not results:
            click.echo("  (No required dependencies for this platform)")
            continue

        for pkg, installed in results.items():
            status = "✓" if installed else "✗"
            click.echo(f"  {status} {pkg}")

            if not installed:
                all_missing.append(pkg)

    if not all_missing:
        click.echo("\n✅ All dependencies satisfied")
        return

    if dry_run:
        click.echo(f"\nWould install: {', '.join(all_missing)}")
        return

    # Offer to install
    success, message = install_missing_dependencies(
        all_missing,
        interactive=not yes,
        verbose=verbose
    )

    if success:
        click.echo("\n✅ Dependencies installed successfully")
    else:
        click.echo(f"\n❌ Installation failed: {message}")


# Diagnostics group
@voice_mode_main_cli.group()
@click.help_option('-h', '--help', help='Show this message and exit')
def diag():
    """Diagnostic tools for voicemode."""
    pass


@diag.command()
def info():
    """Show voicemode installation information."""
    from voice_mode.tools.diagnostics import voice_mode_info
    result = asyncio.run(voice_mode_info.fn())
    click.echo(result)


@diag.command()
def devices():
    """List available audio input and output devices."""
    from voice_mode.tools.devices import check_audio_devices
    result = asyncio.run(check_audio_devices.fn())
    click.echo(result)


@diag.command()
def registry():
    """Show voice provider registry with all discovered endpoints."""
    from voice_mode.tools.voice_registry import voice_registry
    result = asyncio.run(voice_registry.fn())
    click.echo(result)


@diag.command()
def dependencies():
    """Check system audio dependencies and provide installation guidance."""
    import json
    from voice_mode.tools.dependencies import check_audio_dependencies
    result = asyncio.run(check_audio_dependencies.fn())
    
    if isinstance(result, dict):
        # Format the dictionary output nicely
        click.echo("System Audio Dependencies Check")
        click.echo("=" * 50)
        
        click.echo(f"\nPlatform: {result.get('platform', 'Unknown')}")
        
        if 'packages' in result:
            click.echo("\nSystem Packages:")
            for pkg, status in result['packages'].items():
                symbol = "✅" if status else "❌"
                click.echo(f"  {symbol} {pkg}")
        
        if 'missing_packages' in result and result['missing_packages']:
            click.echo("\n❌ Missing Packages:")
            for pkg in result['missing_packages']:
                click.echo(f"  - {pkg}")
            if 'install_command' in result:
                click.echo(f"\nInstall with: {result['install_command']}")
        
        if 'pulseaudio' in result:
            pa = result['pulseaudio']
            click.echo(f"\nPulseAudio Status: {'✅ Running' if pa.get('running') else '❌ Not running'}")
            if pa.get('version'):
                click.echo(f"  Version: {pa['version']}")
        
        if 'diagnostics' in result and result['diagnostics']:
            click.echo("\nDiagnostics:")
            for diag in result['diagnostics']:
                click.echo(f"  - {diag}")
        
        if 'recommendations' in result and result['recommendations']:
            click.echo("\nRecommendations:")
            for rec in result['recommendations']:
                click.echo(f"  - {rec}")
    else:
        # Fallback for string output
        click.echo(str(result))


# Legacy CLI for voicemode-cli command
@click.group()
@click.version_option()
@click.help_option('-h', '--help')
def cli():
    """Voice Mode CLI - Manage conversations, view logs, and analyze voice interactions."""
    pass


# Import subcommand groups
from voice_mode.cli_commands import exchanges as exchanges_cmd
from voice_mode.cli_commands import transcribe as transcribe_cmd
from voice_mode.cli_commands import history as history_cmd
from voice_mode.cli_commands import status as status_cmd

# Add subcommands to legacy CLI
cli.add_command(exchanges_cmd.exchanges)
cli.add_command(transcribe_cmd.transcribe)

# Add exchanges to main CLI
voice_mode_main_cli.add_command(exchanges_cmd.exchanges)
voice_mode_main_cli.add_command(history_cmd.history)

# Add unified status command
voice_mode_main_cli.add_command(status_cmd.status)

# Note: We'll add these commands after the groups are defined
# audio group will get transcribe and play commands


# Now add the subcommands to their respective groups
# Add transcribe as top-level command
transcribe_audio_cmd = transcribe_cmd.transcribe.commands['audio']
transcribe_audio_cmd.name = 'transcribe'
voice_mode_main_cli.add_command(transcribe_audio_cmd)

# Converse command - direct voice conversation from CLI
@voice_mode_main_cli.command()
@click.help_option('-h', '--help')
@click.option('--message', '-m', default="Hello! How can I help you today?", help='Initial message to speak')
@click.option('--wait/--no-wait', default=True, help='Wait for response after speaking')
@click.option('--duration', '-d', type=float, default=DEFAULT_LISTEN_DURATION, help='Listen duration in seconds')
@click.option('--min-duration', type=float, default=MIN_RECORDING_DURATION, help='Minimum listen duration before silence detection')
@click.option('--voice', help='TTS voice to use (e.g., nova, shimmer, af_sky)')
@click.option('--tts-provider', type=click.Choice(['openai', 'kokoro']), help='TTS provider')
@click.option('--tts-model', help='TTS model (e.g., tts-1, tts-1-hd)')
@click.option('--tts-instructions', help='Tone/style instructions for gpt-4o-mini-tts')
@click.option('--audio-feedback/--no-audio-feedback', default=None, help='Enable/disable audio feedback')
@click.option('--audio-format', help='Audio format (pcm, mp3, wav, flac, aac, opus)')
@click.option('--disable-silence-detection', is_flag=True, help='Disable silence detection')
@click.option('--speed', type=float, help='Speech rate (0.25 to 4.0)')
@click.option('--vad-aggressiveness', type=int, help='VAD aggressiveness (0-3)')
@click.option('--skip-tts/--no-skip-tts', default=None, help='Skip TTS and only show text')
@click.option('--continuous', '-c', is_flag=True, help='Continuous conversation mode')
def converse(message, wait, duration, min_duration, voice, tts_provider,
            tts_model, tts_instructions, audio_feedback, audio_format, disable_silence_detection,
            speed, vad_aggressiveness, skip_tts, continuous):
    """Have a voice conversation directly from the command line.

    Examples:

        # Simple conversation
        voicemode converse

        # Speak a message without waiting
        voicemode converse -m "Hello there!" --no-wait

        # Continuous conversation mode
        voicemode converse --continuous

        # Use specific voice
        voicemode converse --voice nova
    """
    # Check core dependencies before running
    from voice_mode.utils.dependencies.checker import check_component_dependencies

    results = check_component_dependencies('core')
    missing = [pkg for pkg, installed in results.items() if not installed]

    if missing:
        click.echo(f"⚠️  Missing core dependencies: {', '.join(missing)}")
        click.echo("   Run 'voicemode deps' to install them")
        return

    from voice_mode.tools.converse import converse as converse_fn
    
    async def run_conversation():
        """Run the conversation asynchronously."""
        # Suppress the spurious aiohttp warning that appears on startup
        # This warning is a false positive from asyncio detecting an unclosed
        # session that was likely created during module import
        import logging
        logging.getLogger('asyncio').setLevel(logging.CRITICAL)

        # Enable INFO logging for converse command to show progress
        logging.getLogger('voicemode').setLevel(logging.INFO)

        try:
            if continuous:
                # Continuous conversation mode
                click.echo("🎤 Starting continuous conversation mode...")
                click.echo("   Press Ctrl+C to exit\n")
                
                # First message
                result = await converse_fn.fn(
                    message=message,
                    wait_for_response=True,
                    listen_duration_max=duration,
                    listen_duration_min=min_duration,
                    voice=voice,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                    tts_instructions=tts_instructions,
                    chime_enabled=audio_feedback,
                    audio_format=audio_format,
                    disable_silence_detection=disable_silence_detection,
                    speed=speed,
                    vad_aggressiveness=vad_aggressiveness,
                    skip_tts=skip_tts
                )
                
                if result and "Voice response:" in result:
                    click.echo(f"You: {result.split('Voice response:')[1].split('|')[0].strip()}")
                
                # Continue conversation
                while True:
                    # Wait for user's next input
                    result = await converse_fn.fn(
                        message="",  # Empty message for listening only
                        wait_for_response=True,
                        listen_duration_max=duration,
                        listen_duration_min=min_duration,
                        voice=voice,
                        tts_provider=tts_provider,
                        tts_model=tts_model,
                        tts_instructions=tts_instructions,
                        chime_enabled=audio_feedback,
                        audio_format=audio_format,
                        disable_silence_detection=disable_silence_detection,
                        speed=speed,
                        vad_aggressiveness=vad_aggressiveness,
                        skip_tts=skip_tts
                    )
                    
                    if result and "Voice response:" in result:
                        user_text = result.split('Voice response:')[1].split('|')[0].strip()
                        click.echo(f"You: {user_text}")
                        
                        # Check for exit commands
                        if user_text.lower() in ['exit', 'quit', 'goodbye', 'bye']:
                            await converse_fn.fn(
                                message="Goodbye!",
                                wait_for_response=False,
                                voice=voice,
                                tts_provider=tts_provider,
                                tts_model=tts_model,
                                audio_format=audio_format,
                                speed=speed,
                                skip_tts=skip_tts
                            )
                            break
            else:
                # Single conversation
                result = await converse_fn.fn(
                    message=message,
                    wait_for_response=wait,
                    listen_duration_max=duration,
                    listen_duration_min=min_duration,
                    voice=voice,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                    tts_instructions=tts_instructions,
                    chime_enabled=audio_feedback,
                    audio_format=audio_format,
                    disable_silence_detection=disable_silence_detection,
                    speed=speed,
                    vad_aggressiveness=vad_aggressiveness,
                    skip_tts=skip_tts
                )
                
                # Display result
                if result:
                    if "Voice response:" in result:
                        # Extract the response text and timing info
                        parts = result.split('|')
                        response_text = result.split('Voice response:')[1].split('|')[0].strip()
                        timing_info = parts[1].strip() if len(parts) > 1 else ""
                        
                        click.echo(f"\n📢 Spoke: {message}")
                        if wait:
                            click.echo(f"🎤 Heard: {response_text}")
                        if timing_info:
                            click.echo(f"⏱️  {timing_info}")
                    else:
                        click.echo(result)
                        
        except KeyboardInterrupt:
            click.echo("\n\n👋 Conversation ended")
        except Exception as e:
            click.echo(f"❌ Error: {e}", err=True)
            import traceback
            if os.environ.get('VOICEMODE_DEBUG'):
                traceback.print_exc()
    
    # Run the async function
    asyncio.run(run_conversation())


# Version command
@voice_mode_main_cli.command()
def version():
    """Show VoiceMode version and check for updates."""
    import requests

    # Use the same version that --version shows
    click.echo(f"VoiceMode version: {__version__}")

    # Check for updates if not in development mode
    if not ("dev" in __version__ or "dirty" in __version__):
        try:
            response = requests.get(
                "https://pypi.org/pypi/voice-mode/json",
                timeout=2
            )
            if response.status_code == 200:
                latest_version = response.json()["info"]["version"]
                
                # Simple version comparison (works for semantic versioning)
                if latest_version != __version__:
                    click.echo(f"Latest version: {latest_version} available")
                    click.echo("Run 'voicemode update' to update")
                else:
                    click.echo("You are running the latest version")
        except (requests.RequestException, KeyError, ValueError):
            # Fail silently if we can't check for updates
            pass


# Update command
@voice_mode_main_cli.command()
@click.help_option('-h', '--help')
@click.option('--force', is_flag=True, help='Force reinstall even if already up to date')
def update(force):
    """Update Voice Mode to the latest version.
    
    Automatically detects installation method (UV tool, UV pip, or regular pip)
    and uses the appropriate update command.
    """
    import subprocess
    import requests
    from pathlib import Path
    from importlib.metadata import version as get_version, PackageNotFoundError
    
    def detect_uv_tool_installation():
        """Detect if running from a UV tool installation."""
        prefix_path = Path(sys.prefix).resolve()
        uv_tools_base = Path.home() / ".local" / "share" / "uv" / "tools"
        
        # Check if sys.prefix is within UV tools directory
        if uv_tools_base in prefix_path.parents or prefix_path.parent == uv_tools_base:
            # Find the tool directory
            tool_dir = prefix_path if prefix_path.parent == uv_tools_base else None
            
            if not tool_dir:
                for parent in prefix_path.parents:
                    if parent.parent == uv_tools_base:
                        tool_dir = parent
                        break
            
            if tool_dir:
                # Verify with uv-receipt.toml
                receipt_file = tool_dir / "uv-receipt.toml"
                if receipt_file.exists():
                    # Parse tool name from receipt or use directory name
                    try:
                        with open(receipt_file) as f:
                            content = f.read()
                            import re
                            match = re.search(r'name = "([^"]+)"', content)
                            tool_name = match.group(1) if match else tool_dir.name
                            return True, tool_name
                    except Exception:
                        return True, tool_dir.name
        
        return False, None
    
    def detect_uv_venv():
        """Detect if running in a UV-managed virtual environment."""
        # Check if we're in a venv
        if sys.prefix == sys.base_prefix:
            return False
        
        # Check for UV markers in pyvenv.cfg
        pyvenv_cfg = Path(sys.prefix) / "pyvenv.cfg"
        if pyvenv_cfg.exists():
            try:
                with open(pyvenv_cfg) as f:
                    content = f.read()
                    if "uv" in content.lower() or "managed by uv" in content:
                        return True
            except Exception:
                pass
        
        return False
    
    def check_uv_available():
        """Check if UV is available."""
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    # Get current version
    try:
        current_version = get_version("voice-mode")
    except PackageNotFoundError:
        current_version = "development"
    
    # Check if update needed (unless forced)
    if not force and current_version != "development":
        try:
            response = requests.get(
                "https://pypi.org/pypi/voice-mode/json",
                timeout=2
            )
            if response.status_code == 200:
                latest_version = response.json()["info"]["version"]
                if latest_version == current_version:
                    click.echo(f"Already running the latest version ({current_version})")
                    return
        except (requests.RequestException, KeyError, ValueError):
            pass  # Continue with update if we can't check
    
    # Detect installation method
    is_uv_tool, tool_name = detect_uv_tool_installation()
    
    if is_uv_tool:
        # UV tool installation - use uv tool upgrade
        click.echo(f"Updating Voice Mode (UV tool: {tool_name})...")
        
        result = subprocess.run(
            ["uv", "tool", "upgrade", tool_name],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            try:
                new_version = get_version("voice-mode")
                click.echo(f"✅ Successfully updated to version {new_version}")
            except PackageNotFoundError:
                click.echo("✅ Successfully updated Voice Mode")
        else:
            click.echo(f"❌ Update failed: {result.stderr}")
            click.echo(f"Try running manually: uv tool upgrade {tool_name}")
    
    elif detect_uv_venv():
        # UV-managed virtual environment
        click.echo("Updating Voice Mode (UV virtual environment)...")
        
        result = subprocess.run(
            ["uv", "pip", "install", "--upgrade", "voice-mode"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            try:
                new_version = get_version("voice-mode")
                click.echo(f"✅ Successfully updated to version {new_version}")
            except PackageNotFoundError:
                click.echo("✅ Successfully updated Voice Mode")
        else:
            click.echo(f"❌ Update failed: {result.stderr}")
            click.echo("Try running: uv pip install --upgrade voice-mode")
    
    else:
        # Standard installation - try UV if available, else pip
        has_uv = check_uv_available()
        
        if has_uv:
            click.echo("Updating Voice Mode (using UV)...")
            result = subprocess.run(
                ["uv", "pip", "install", "--upgrade", "voice-mode"],
                capture_output=True,
                text=True
            )
        else:
            click.echo("Updating Voice Mode (using pip)...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "voice-mode"],
                capture_output=True,
                text=True
            )
        
        if result.returncode == 0:
            try:
                new_version = get_version("voice-mode")
                click.echo(f"✅ Successfully updated to version {new_version}")
            except PackageNotFoundError:
                click.echo("✅ Successfully updated Voice Mode")
        else:
            click.echo(f"❌ Update failed: {result.stderr}")
            if has_uv:
                click.echo("Try running: uv pip install --upgrade voice-mode")
            else:
                click.echo("Try running: pip install --upgrade voice-mode")


# Completions command
@voice_mode_main_cli.command()
@click.help_option('-h', '--help')
@click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']))
@click.option('--install', is_flag=True, help='Install completion script to the appropriate location')
def completions(shell, install):
    """Generate or install shell completion scripts.
    
    Examples:
        voicemode completions bash              # Output bash completion to stdout
        voicemode completions bash --install    # Install to ~/.bash_completion.d/
        voicemode completions zsh --install     # Install to ~/.zfunc/
        voicemode completions fish --install    # Install to ~/.config/fish/completions/
    """
    from pathlib import Path
    
    # Generate completion scripts based on shell type
    if shell == 'bash':
        completion_script = '''# bash completion for voicemode
_voicemode_completion() {
    local IFS=$'\\n'
    local response
    
    response=$(env _VOICEMODE_COMPLETE=bash_complete COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD voicemode 2>/dev/null)
    
    for completion in $response; do
        IFS=',' read type value <<< "$completion"
        
        if [[ $type == 'plain' ]]; then
            COMPREPLY+=("$value")
        elif [[ $type == 'file' ]]; then
            COMPREPLY+=("$value")
        elif [[ $type == 'dir' ]]; then
            COMPREPLY+=("$value")
        fi
    done
    
    return 0
}

complete -o default -F _voicemode_completion voicemode
'''
    
    elif shell == 'zsh':
        completion_script = '''#compdef voicemode
# zsh completion for voicemode

_voicemode() {
    local -a response
    response=(${(f)"$(env _VOICEMODE_COMPLETE=zsh_complete COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) voicemode 2>/dev/null)"})
    
    for completion in $response; do
        IFS=',' read type value <<< "$completion"
        compadd -U -- "$value"
    done
}

compdef _voicemode voicemode
'''
    
    elif shell == 'fish':
        completion_script = '''# fish completion for voicemode
function __fish_voicemode_complete
    set -l response (env _VOICEMODE_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) voicemode 2>/dev/null)
    
    for completion in $response
        echo $completion
    end
end

complete -c voicemode -f -a '(__fish_voicemode_complete)'
'''
    
    if install:
        # Define installation locations for each shell
        locations = {
            'bash': '~/.bash_completion.d/voicemode',
            'zsh': '~/.zfunc/_voicemode',
            'fish': '~/.config/fish/completions/voicemode.fish'
        }
        
        install_path = Path(locations[shell]).expanduser()
        install_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write completion script to file
        install_path.write_text(completion_script)
        click.echo(f"✅ Installed {shell} completions to {install_path}")
        
        # Provide shell-specific instructions
        if shell == 'bash':
            click.echo("\nTo activate now, run:")
            click.echo(f"  source {install_path}")
            click.echo("\nTo activate permanently, add to ~/.bashrc:")
            click.echo(f"  source {install_path}")
        elif shell == 'zsh':
            click.echo("\nTo activate now, run:")
            click.echo("  autoload -U compinit && compinit")
            click.echo("\nMake sure ~/.zfunc is in your fpath (add to ~/.zshrc):")
            click.echo("  fpath=(~/.zfunc $fpath)")
        elif shell == 'fish':
            click.echo("\nCompletions will be active in new fish sessions.")
            click.echo("To activate now, run:")
            click.echo(f"  source {install_path}")
    else:
        # Output completion script to stdout
        click.echo(completion_script)


