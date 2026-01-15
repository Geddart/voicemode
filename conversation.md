# VoiceMode Session Log - January 2026

## SESSION STATUS (January 15, 2026)

### CURRENT: Project Announcement for Queued Messages COMPLETE

**When TTS messages are queued behind audio from a DIFFERENT project, the project name is now announced.**

Example: "Update from voicemode: I've fixed the bug"

#### Changes Made (January 15, 2026 - Session 3)

1. **`voice_mode/audio_manager/service.py`**
   - `reserve_slot()` now computes `should_announce` flag
   - Checks if audio from different project is currently playing
   - Checks if audio from different project is ahead in queue
   - Returns `should_announce` in result dict

2. **`voice_mode/core.py`**
   - After reserving slot, checks `should_announce` flag
   - Prepends "Update from {PROJECT_NAME}: " to message when true

#### Key Design Decision: Project-Aware Logic

Only announces when a DIFFERENT project's audio is ahead or playing. This prevents:
- Same-window sequential messages from announcing
- Same-window background mode rapid fire from announcing
- Same-project chimes followed by TTS from announcing

#### Test Status
- 457 passing, 17 failing (no regressions from previous session)

#### Testing Note (January 15, 2026 - Session 4)
- **Project announcement verified working** after audio manager restart
- The code was correct but the audio manager service was running old code
- Fix: `service audio-manager restart` (or via MCP tool)

#### Multi-Window Fix (January 15, 2026 - Session 4)

**Problem:** All Claude windows sent "voicemode" as project name because MCP server config uses `--directory voicemode`.

**Solution:** Added unique session ID per MCP server instance.

**Changes:**
1. **`voice_mode/config.py`**
   - Added `SESSION_ID = uuid.uuid4()[:8]` - unique per MCP server
   - Added `get_session_project_id()` - returns `"{project}:{session_id}"`

2. **`voice_mode/audio_router.py`**
   - Changed to use `get_session_project_id()` for audio queue identification
   - Each Claude window now has unique ID like `voicemode:abc123`

3. **`voice_mode/core.py`**
   - Still uses `get_project_name()` for announcement text (no session ID)

4. **`voice_mode/tools/service.py`**
   - Implemented `logs` action for audio-manager
   - Audio manager now logs to `~/.voicemode/logs/audio-manager/`

5. **`voice_mode/audio_manager/service.py`**
   - Added debug logging for `should_announce` decision

**To test:** Both Claude windows must restart to get new session IDs.

---

### PREVIOUS: Audio Architecture Overhaul COMPLETE

**All TTS audio now flows through centralized audio manager** (January 15, 2026)

Implemented clean architecture where ALL audio (TTS, chimes, system sounds) routes through the audio manager service. This provides:
- Multi-window queuing (no audio overlap between Claude windows)
- Fn key pause/resume for dictation
- Proper blocking support (/wait endpoint)
- Priority queuing (chimes play before TTS)

### Changes Made

#### New Files
- `voice_mode/audio_router.py` - Unified interface for routing all audio through audio manager

#### Modified Files

1. **`voice_mode/audio_manager/player.py`** (BUG FIX)
   - Fixed critical bug: `pause()` and `resume()` now always set `_is_paused` state
   - Previously, if nothing was playing, pause() returned early without setting state
   - This caused fn key press BEFORE audio arrives to be ignored

2. **`voice_mode/audio_manager/service.py`**
   - Added item completion tracking with `_item_events` dict
   - Added `wait_for_item()` method for blocking wait support
   - Added `_cleanup_item_event()` to prevent memory leaks (60s cleanup)
   - Event created at queue time (before /wait can be called)

3. **`voice_mode/audio_manager/api.py`**
   - Added `POST /wait/{item_id}` endpoint
   - Returns `{"completed": true}` when audio finishes
   - Supports timeout query param (default 120s)

4. **`voice_mode/audio_manager/client.py`**
   - Added `wait_for_item(item_id, timeout)` method
   - HTTP POST to `/wait/{item_id}?timeout={timeout}`

5. **`voice_mode/streaming.py`**
   - Removed `AudioStreamPlayer` class (dead code)
   - Removed direct sounddevice usage
   - `stream_pcm_audio()` - buffers chunks, routes through audio_router
   - `stream_with_buffering()` - buffers, decodes, routes through audio_router
   - Both support `blocking` parameter

6. **`voice_mode/core.py`**
   - `play_tts_chime()` - routes through audio_router (priority="high", blocking=False)
   - `play_chime_start()` - routes through audio_router
   - `play_chime_end()` - routes through audio_router
   - `play_system_audio()` - routes through audio_router

7. **`voice_mode/tools/converse.py`**
   - Removed all Conch imports and logic
   - Removed `conch` parameter from `_run_tts_in_background()`
   - Simplified background mode (no more conch acquisition)
   - Audio manager handles all coordination

8. **`voice_mode/config.py`**
   - Removed `CONCH_ENABLED`, `CONCH_TIMEOUT`, `CONCH_CHECK_INTERVAL`
   - Removed `USE_AUDIO_MANAGER` (always enabled now)
   - Kept: `AUDIO_MANAGER_PORT`, `AUDIO_MANAGER_AUTO_START`, `PAUSE_HOTKEY`

#### Deleted Files
- `voice_mode/conch.py` - File-locking system replaced by audio manager
- `tests/test_conch.py` - Tests for removed conch system

### Test Status

**457 tests passing**, 17 failing (expected - tests need updating for new architecture)

Failing tests are in:
- `test_converse_critical_path.py` - Tests expect old conch behavior
- `test_speed_parameter.py` - Tests don't set `background=False` explicitly
- `test_wait_repeat_functionality.py` - Tests mock `NonBlockingAudioPlayer` instead of `audio_router`
- `test_endpoint_info_attributes.py` - Related to converse behavior

### Manual Testing Results (January 15, 2026)

**Audio manager required restart** to pick up code changes.

1. ✅ **Single window TTS**: Working
2. ✅ **Fn key pause during playback**: Working - press fn pauses, release resumes

### Changes Made (January 15, 2026 - Session 2)

**Implemented reservation system for gapless multi-window playback:**

1. **queue.py** - Added reservation support:
   - `reserve()` - Reserve slot before TTS generation
   - `fill()` - Fill slot with audio when ready
   - Queue waits for items to be filled in order

2. **service.py** - Added service methods:
   - `reserve_slot()` and `fill_slot()` delegate to queue
   - Chime rate-limiting (centralized across windows)

3. **api.py** - Added endpoints:
   - `POST /reserve` - Reserve a queue slot
   - `POST /fill/{item_id}` - Fill reserved slot with audio
   - `POST /chime-allowed` - Check/record chime permission

4. **client.py** - Added client methods:
   - `reserve()`, `fill()`, `chime_allowed()`

5. **audio_router.py** - Added helpers:
   - `reserve_slot()`, `fill_slot()`, `fill_slot_samples()`

6. **core.py** - Updated TTS flow:
   - Reserves slot BEFORE TTS generation
   - Fills slot AFTER audio is ready
   - Both streaming and buffered paths use reservation

7. **streaming.py** - Updated to accept item_id:
   - `stream_pcm_audio()`, `stream_tts_audio()`, `stream_with_buffering()`
   - Uses fill_slot when item_id provided

### Testing Required

1. **Chime rate-limiting**: Wait 60s, trigger from two windows - only ONE chime
2. **Multi-window ordering**: Window 1 (long), Window 2 (short) - Window 1 plays first
3. **No gaps**: Messages play back-to-back without pauses

4. **Multi-window queuing**:
   - Open 2 Claude windows (different projects)
   - Trigger TTS from both rapidly (within 1 second)
   - Verify messages queue (no overlap)
   - `curl localhost:8881/status` should show queue_length > 0 during overlap

5. **Blocking behavior**:
   - `curl localhost:8881/status` in a loop
   - Trigger TTS with background=false (default)
   - Verify converse() only returns AFTER audio finishes

6. **Chime rate-limiting**:
   - Wait 60+ seconds
   - Speak → chime plays first
   - Speak again within 60s → no chime

7. **Audio manager auto-restart**:
   - Kill audio manager: `pkill -f "voice_mode.audio_manager"`
   - Trigger TTS → should auto-restart and play

### Architecture

```
BEFORE (broken):
  converse() → streaming.py → sounddevice (direct, no coordination)
  Conch file-locking (bypassed when audio manager enabled)

AFTER (clean):
  ALL audio → audio_router → AudioManagerClient.speak() → HTTP /speak
           → Audio Manager queue (thread-safe, priority-ordered)
           → AudioPlaybackManager.play() → sounddevice
           → HotkeyMonitor for pause/resume
```

---

## Previous Sessions

(Previous content below for reference)

### Fn Key Pause Feature (January 15, 2026)

Holding the MacBook fn key pauses TTS audio, releasing resumes it.

**Audio Manager Status:**
- Running on port 8881
- Fn key detection working via macOS event tap
- Creates/removes `~/.voicemode/dictating.lock` when fn pressed/released

**Important Note:**
- Logitech external keyboard fn key does NOT work (firmware-level handling)
- MacBook built-in fn key works correctly (flag 0x800100 detected)

---

### Audio Manager HTTP API (port 8881)
- `GET /health` - Health check
- `GET /status` - Current status (playing, queue, dictation, hotkey)
- `POST /speak` - Queue audio for playback (immediate)
- `POST /reserve` - Reserve queue slot before TTS generation
- `POST /fill/{item_id}` - Fill reserved slot with audio
- `POST /wait/{item_id}` - Wait for specific audio to finish
- `POST /chime-allowed` - Check/record chime permission (rate-limiting)
- `POST /pause` - Pause playback
- `POST /resume` - Resume playback
- `POST /clear` - Clear queue
- `POST /stop` - Stop playback

### Service Management
```bash
# Via MCP tool
service audio-manager status
service audio-manager start
service audio-manager stop
service audio-manager restart

# Directly
uv run python -m voice_mode.audio_manager --port 8881 --hotkey fn --debug
```

---

## Test Commands

```bash
# Check audio manager status
curl localhost:8881/status

# Check audio manager health
curl localhost:8881/health

# Run tests (some expected failures due to architecture change)
make test

# Test chime rate-limiting (should only chime first time)
uv run python -c "
import asyncio
from voice_mode.core import play_tts_chime
asyncio.run(play_tts_chime())  # Should play
asyncio.run(play_tts_chime())  # Should skip (within 60s)
"
```

---

## Services Running
- Kokoro TTS on port 8880 (working)
- Audio Manager on port 8881 (handles queuing and pause)
- Wispr Flow handles voice input (external)
