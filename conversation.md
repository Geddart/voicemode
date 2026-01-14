# VoiceMode Session Log - January 2026

## SESSION STATUS (January 14, 2026)

**All features working!** ✅

### Completed Features
1. **Background TTS** - Returns in ~0.004s, audio plays independently
2. **Startup chime** - Plays while TTS generates, no segfault
3. **Multi-window queuing** - Messages queue and announce project name

### To Continue Development
Just say: "Read conversation.md for context" - all details are below.

---

## Debugging Progress

### Feature 1: Background TTS Playback

**Status:** ✅ FULLY WORKING (January 14, 2026)

**What we tried:**
1. Added `background` parameter through the call chain:
   - `converse()` in tools/converse.py
   - `text_to_speech_with_failover()` in tools/converse.py
   - `simple_tts_failover()` in simple_failover.py
   - `text_to_speech()` in core.py

2. In `text_to_speech()`, when `background=True`:
   - Call `player.play(samples, rate, blocking=False)`
   - Skip `player.wait()` - return immediately
   - Set `metrics['background'] = True`

**Issue found:** Streaming mode doesn't support background!
- Default: `STREAMING_ENABLED=true` with PCM format
- Streaming path (`stream_tts_audio`) doesn't pass `background` parameter
- Streaming always waits for completion

**Fix applied:** Disable streaming when background=True (core.py line 269):
```python
use_streaming = STREAMING_ENABLED and validated_format in ["opus", "mp3", "pcm", "wav"] and not background
```

**Test result:** With chime disabled (`VOICEMODE_TTS_CHIME=false`), background mode works:
```
Result: ✓ Speaking in background (gen: 1.5s, playing in background)
```

**Final fix (January 14):** Previous "background" only skipped playback wait, not TTS generation wait.
- Added `_run_tts_in_background()` helper function in converse.py
- When `background=True`, spawn entire TTS operation as `asyncio.create_task()`
- Return immediately with "✓ Speaking in background"
- Background task handles conch, TTS generation, and playback independently

**Test results after final fix:**
- `background=True`: Returns in **0.005s** (instant!)
- `background=False`: Returns after 4.38s (waits for playback)
- Audio plays correctly in both modes

**Default changed (January 14):** Changed `background` default from `False` to `True` so Claude Code returns immediately without needing to explicitly request it. Claude Code can now continue working while audio plays.

### Feature 3: Multi-Window Audio Queuing

**Status:** ✅ IMPLEMENTED (January 14, 2026)

**What we implemented:**
1. Auto-detect project name (git repo root → CWD → "unknown")
2. Added `queue` parameter to converse() (default: True)
3. When message has to wait for another, prepend "Message from {project}:"
4. Updated Conch to store project name in lock file

**Test results:**
- First window starts speaking
- Second window detects conch held, waits for first to finish
- Second window announces: "Message from voicemode: ..."
- Messages never overlap or get rejected

### Feature 2: Startup Chime

**Status:** ✅ VERIFIED WORKING (January 14, 2026) - Root cause identified and patched in `audio_player.py`

**What we implemented:**
1. Added `play_tts_chime()` function in core.py (lines 779-828)
2. Called at start of `text_to_speech()` (line 215)
3. Config options: `TTS_CHIME_ENABLED=true`, `TTS_CHIME_NAME=Pling`
4. Chime files in: `voice_mode/data/soundfonts/default/chimes/`

**Issue found:** Concurrent audio playback causes SEGFAULT (exit code 139)
- Chime plays with `NonBlockingAudioPlayer(blocking=False)`
- TTS then tries to play with another `NonBlockingAudioPlayer`
- sounddevice crashes when two streams are active

**Test results:**
- Chime alone: WORKS (`await play_tts_chime()` plays fine)
- Chime + TTS together: SEGFAULT
- Chime disabled + TTS: WORKS

**What we tried:**
1. Made chime blocking (`blocking=True`) - WORKS but defeats purpose (chime is 3.78s long!)
2. Reverted to non-blocking - need to find concurrent audio solution

**Root cause identified (January 14):**
- `NonBlockingAudioPlayer` doesn't keep itself alive when `blocking=False`
- When `play_tts_chime()` returns, the `player` variable goes out of scope
- Python's garbage collector frees the player while sounddevice stream is still active
- When TTS then creates a second stream, PortAudio accesses freed memory → SEGFAULT

**Fix applied to `voice_mode/audio_player.py`:**
- Added module-level `_active_players` list to keep players alive
- Players register themselves in `play()` when `blocking=False`
- Players unregister in callback when playback completes
- Also unregister in `wait()` and `stop()` for manual cleanup

**Test results after fix:**
- Two concurrent players: SUCCESS (both play without crash)
- GC during playback: SUCCESS (registry keeps player alive)
- Different sample rates: SUCCESS (44100Hz chime + 24000Hz TTS)
- Full integration test (January 14): SUCCESS
  - `VOICEMODE_TTS_CHIME=true` with converse tool
  - Chime plays in background, TTS generates, speech plays
  - Result: "✓ Message spoken successfully (gen: 1.2s, play: 2.8s)"

---

## Key Findings

### MCP Server "Connection closed" Error
This is caused by SEGFAULT (exit code 139) from concurrent audio playback, NOT a network issue.

### Pling.m4a Duration
The Pling.m4a file is **3.78 seconds** - too long for a startup chime! Need a shorter sound.

### Code Paths
- **Streaming mode** (default): Uses `stream_tts_audio()` - doesn't support background
- **Buffered mode**: Uses `text_to_speech()` with NonBlockingAudioPlayer - supports background

---

## Files Modified This Session

- `voice_mode/audio_player.py`:
  - Added `_active_players` registry to keep players alive during non-blocking playback
  - Added `_register()` and `_unregister()` methods
  - Players auto-register in `play()` when `blocking=False`
  - Players auto-unregister when playback completes or is stopped

- `voice_mode/tools/converse.py`:
  - Added `_run_tts_in_background()` helper function (~line 422)
  - Modified `converse()` to spawn background task when `background=True`
  - Returns immediately instead of waiting for TTS generation
  - Added `queue` parameter (default: True) for multi-window coordination
  - Prepends "Message from {project}:" when message was queued

- `voice_mode/conch.py`:
  - Added `project` field to lock file
  - Auto-detects project name from git repo or CWD

- `voice_mode/core.py`:
  - Added `play_tts_chime()` function (lines 779-828)
  - Call chime at TTS start (line 215)
  - Disable streaming when background=True (line 269)

- `voice_mode/config.py`:
  - Added `TTS_CHIME_ENABLED` config (line 436)
  - Added `TTS_CHIME_NAME` config (line 437)

- `voice_mode/data/soundfonts/default/chimes/`:
  - Added Pling.m4a (3.78s - TOO LONG)
  - Added echo-chime-chime-89653.mp3
  - Added mystical-chime-196405.mp3
  - Added public-announcement-chime-182478.mp3

---

## Next Steps to Try

1. ~~**Fix concurrent audio:**~~ ✅ DONE - Added player registry to `audio_player.py`

2. ~~**Test in fresh session:**~~ ✅ DONE - Tested January 14, 2026
   - Chime + TTS work together without segfault
   - Test results: "✓ Message spoken successfully (gen: 1.2s, play: 2.8s)"

3. **Shorter chime:** The Pling.m4a is 3.78s - need to trim it or use a shorter sound (~0.5s ideal)

---

## Test Commands

```bash
# Test chime alone
uv run python -c "
import asyncio
from voice_mode.core import play_tts_chime
asyncio.run(play_tts_chime())
"

# Test TTS with chime disabled
VOICEMODE_TTS_CHIME=false uv run python -c "
import asyncio
from voice_mode.server import mcp
tools = mcp._tool_manager._tools
asyncio.run(tools['converse'].fn(message='test', background=True))
"

# Test TTS with chime enabled (may segfault)
uv run python -c "
import asyncio
from voice_mode.server import mcp
tools = mcp._tool_manager._tools
asyncio.run(tools['converse'].fn(message='test', background=True))
"

# Check chime config
uv run python -c "from voice_mode.config import TTS_CHIME_ENABLED, TTS_CHIME_NAME; print(TTS_CHIME_ENABLED, TTS_CHIME_NAME)"
```

---

## Previous Session Context (for reference)

### MCP Server Fixes (Already Applied)
- FastMCP banner: `show_banner=False` in server.py
- Module identity: `sys.modules["voice_mode.server"] = sys.modules[__name__]`
- Logging to stderr: `stream=sys.stderr` in config.py

### Services Running
- Kokoro TTS on port 8880 (working)
- Wispr Flow handles voice input (external)
