# VoiceMode Session Log - January 2026

## SESSION STATUS (January 15, 2026)

### COMPLETED: Final STT/Whisper Cleanup (Session 10)

**Goal:** Third and final pass to remove ALL remaining STT/Whisper/CLI references from the codebase.

**Critical Fixes (Would Have Caused Runtime Errors):**

1. **voice_mode/tools/diagnostics.py** - Removed iteration over "stt" service type (KeyError)
2. **voice_mode/resources/statistics.py** - Removed stt_processing block references (AttributeError)

**Scripts Deleted:**
- scripts/view-exchanges (CLI redirect)
- scripts/tail-exchanges (CLI redirect)
- scripts/tail-exchanges-pretty (CLI redirect)

**Source Files Cleaned:**

1. **voice_mode/pronounce.py** - Complete TTS-only rewrite:
   - Removed STT direction validation
   - Removed STT rule storage
   - Removed process_stt() method
   - Updated list_rules() and test_rule() to TTS-only

2. **voice_mode/conversation_logger.py** - Updated docstrings to TTS-only

3. **scripts/view_event_logs.py** - Removed STT event processing:
   - Removed stt_processing metric
   - Removed STT_COMPLETE event handling

4. **tests/test_tts_stability.py** - Removed STT client mocking (count 2 → 1)

5. **tests/test_pronunciation.py** - Complete rewrite for TTS-only

**Configuration Files Cleaned:**

1. **voice_mode/dependencies.yaml** - Removed Whisper/LiveKit sections (~150 lines)

2. **voice_mode/data/versions.json** - Removed Whisper service entries:
   - com.voicemode.whisper.plist
   - voicemode-whisper.service
   - start-whisper-with-health-check.sh

3. **server.json** - Updated to TTS-only:
   - Description: "TTS via MCP" (was "STT/TTS via MCP")
   - Removed VOICEMODE_WHISPER_MODEL variable
   - Removed VOICEMODE_DISABLE_SILENCE_DETECTION variable

**Documentation Updated (6 files):**

1. **CLAUDE.md** - TTS-only architecture, removed Whisper mentions
2. **README.md** - Removed Whisper setup, STT features
3. **docs/reference/cli.md** - Removed transcribe, whisper, livekit, exchanges commands
4. **docs/guides/configuration.md** - Removed STT configuration section, LiveKit
5. **docs/reference/environment.md** - Removed STT and Whisper variables
6. **skills/voicemode/SKILL.md** - Updated to Kokoro-only service

**Additional Cleanup:**
- voice_mode/__init__.py - Updated docstring
- voice_mode/openai_error_parser.py - Updated fallback messages (Whisper → Kokoro only)

**Final Results:** 242 passed, 43 skipped, 0 failures

**MCP Server:** Starts successfully and returns valid JSON-RPC response

---

### COMPLETED: Deep STT Remnants Cleanup (Session 8 + 9)

**Goal:** After the major TTS-only refactor, review the entire codebase for any remaining STT/Whisper references that were missed.

**Session 8 - What Was Found & Cleaned:**

1. **config.py** - Removed extensive STT config:
   - STT_BASE_URLS, SAVE_TRANSCRIPTIONS, VAD_DEBUG, TRANSCRIPTIONS_DIR
   - Silence detection config (VAD_AGGRESSIVENESS, SILENCE_THRESHOLD_MS, etc.)
   - STT audio format config, save_transcription()
   - LiveKit configuration (not needed for TTS-only)

2. **simple_failover.py** - Removed simple_stt_failover() function

3. **core.py** - Changed get_openai_clients() from 3 args to 2 (removed stt_base_url)

4. **conversation_logger.py** - Removed log_stt() method

5. **statistics.py** - Removed stt_processing, recording_duration fields and stats

6. **event_logger.py** - Removed STT event types and logging functions

7. **utils/__init__.py** - Removed STT logging exports

8. **provider_discovery.py** - Complete rewrite to TTS-only (removed STT registry)

9. **configuration_management.py** - Removed Whisper config references

10. **Deleted Files:**
    - voice_mode/utils/services/coreml_setup.py (Whisper CoreML)
    - voice_mode/utils/services/list_versions.py (Whisper versions)
    - voice_mode/utils/services/version_info.py (Whisper version info)

11. **migration_helpers.py** - Removed Whisper migration code (kept Kokoro only)

12. **resources/configuration.py** - Cleaned STT imports

13. **tools/converse.py** - Fixed get_openai_clients() call signature

**Session 9 - Second Pass Findings:**

**CRITICAL: tools/providers.py** - Completely rewritten to TTS-only:
- Removed STT_BASE_URLS import (was causing ImportError!)
- Removed service_type parameter from refresh_provider_registry()
- Removed STT registry checks from get_provider_details()
- Removed whisper-1 model references

**Scripts Deleted:**
- scripts/test-vad-enhancement.py (imported removed function)
- scripts/test-stt-direct.py (STT test script)
- scripts/conversation_browser.py (STT transcription browser)

**pyproject.toml Cleanup:**
- Removed "livekit" and "stt" from keywords
- Removed LiveKit optional dependency section
- Removed CoreML optional dependency section (was for Whisper)
- Updated aiohttp comment to remove Whisper mention

**Other Fixes:**
- tools/__init__.py - Removed dead sound_fonts loading code
- config.py - Updated comment example to remove 'stt-input'

**Remaining (Low Priority - Not Causing Errors):**
- pronounce.py still has STT rule support (dead code, unused but harmless)
- installer/ directory has Whisper/LiveKit references (separate package)
- Some docs still reference STT (docs/ directory)

**Test Fixes:**
- test_audio_format_config.py - Removed STT_AUDIO_FORMAT tests, updated function signatures
- test_provider_resilience.py - Removed service_type parameters, removed Whisper tests
- test_provider_resilience_simple.py - Same updates
- test_provider_selection.py - Removed Whisper detection test
- test_provider_tools.py - Removed STT registry references
- Added skip markers for tests affected by Python 3.13 / mcp library issue

**Final Results:** 243 passed, 43 skipped, 0 failures

---

### COMPLETED: Massive TTS-Only Refactor (Session 7)

**Goal:** Strip codebase to TTS message announcement only. Remove ALL STT, CLI, history, and unused functionality.

**Final Results:**
- voice_mode/: 21,648 → 13,711 lines (**-7,937 lines, -37%**)
- tests/: 8,854 → 5,972 lines (**-2,882 lines, -33%**)
- **Total removed: ~10,819 lines (~37% of codebase)**

**All tests passing:** 246 passed, 41 skipped, 0 failures

**What Was Removed:**

1. **CLI system** (~2,500 lines)
   - `cli.py`, `cli_commands/` (entire directory)
   - CLI entry points from pyproject.toml

2. **History/Exchange systems** (~2,150 lines)
   - `exchanges/` directory (conversations, reader, filters, formatters, models, stats)
   - `history/` directory (database, loader, search)

3. **Legacy files** (~500 lines)
   - `dictation_monitor.py` (replaced by audio_manager/hotkey.py)
   - `audio_player.py` (inlined into AudioPlaybackManager)

4. **Unused MCP tools** (~1,000 lines)
   - `tools/dependencies.py`, `tools/voice_registry.py`
   - `tools/statistics.py`, `tools/devices.py`
   - `tools/sound_fonts/` directory

5. **STT code from converse.py** (~1,460 lines)
   - Removed: record_audio(), speech_to_text(), prepare_audio_for_stt(), get_stt_config()
   - Removed all wait_for_response logic
   - File went from 1,965 → 506 lines

6. **STT from providers.py** (~113 lines)
   - Removed: get_stt_client, get_provider_by_voice, select_best_voice

7. **Test files for removed functionality** (~2,882 lines)
   - test_diagnostics.py, plus updates to other tests

**Key Refactoring:**
- AudioPlaybackManager now contains all sounddevice playback logic (inlined from audio_player.py)
- `__main__.py` now starts MCP server instead of CLI
- converse() tool simplified to TTS-only (removed ~20 parameters)

**What Was Preserved (All Working):**
- Multi-window audio queuing (reserve/fill pattern)
- Fn key pause/resume (audio_manager/hotkey.py)
- Project announcement for cross-window messages
- /speak-text HTTP endpoint for TTS without Claude Code
- All audio manager functionality on port 8881
- Kokoro TTS service management

---

### PREVIOUS: Fixed Audio Overlap Bug (Session 6)

**Bug:** Multi-window audio was overlapping because repeat functionality bypassed audio manager.

**Root Cause:** In `voice_mode/tools/converse.py` line 1617, the repeat functionality created a `NonBlockingAudioPlayer()` directly, playing audio outside the centralized queue.

**Fix:** Changed repeat functionality to route through `audio_router.play_audio()` instead.

```python
# Before (bypassed audio manager):
player = NonBlockingAudioPlayer()
player.play(data, samplerate, blocking=True)

# After (routes through audio manager):
await audio_router.play_audio(
    audio_data=samples_int16.tobytes(),
    sample_rate=samplerate,
    blocking=True,
)
```

**Investigation Summary:**
- Only ONE audio manager instance running (correct)
- All normal TTS paths go through audio manager (correct)
- Repeat functionality was the ONLY code path bypassing the audio manager
- audio_player.py with NonBlockingAudioPlayer allows concurrent playback by design

**Additional Issue Found:** Audio manager auto-started with `/dev/null` output was stuck in bad state.
- Symptoms: Audio completing in 0.14s instead of 3s, `wait_for_item()` returning immediately
- Fix: Kill and restart audio manager with proper logging
- Root cause: Unknown, but restart resolved the issue
- Recommendation: Monitor audio manager health and auto-restart if needed

**Test Results After Restart:**
- 3 TTS messages: 16.73s total (sequential, including TTS generation)
- 3x1s silence clips: 3.53s total (sequential)
- Audio manager properly shows `playing=True` during playback

### Also Fixed: /speak-text FIFO Ordering Bug

**Bug:** `/speak-text` endpoint generated TTS first, then queued. This meant short messages could jump ahead of long messages.

**Fix:** Changed `/speak-text` to use reserve/fill pattern:
1. Reserve slot BEFORE TTS generation
2. Generate TTS
3. Fill reserved slot

**Test Result:**
- Long message (157 chars) + Short message (9 chars) sent simultaneously
- Long message: position=1, time=13.37s ✅
- Short message: position=2, time=14.57s ✅
- Total: 14.61s (sequential playback confirmed)

### Also: Removed /speak Endpoint

**Why:** The `/speak` endpoint had the same ordering bug - if two clients generated audio at different speeds, the faster one would queue first even if it started later.

**Changes:**
1. Removed `/speak` endpoint from api.py (now returns 404)
2. Updated `AudioManagerClient.speak()` to use reserve/fill internally
3. All audio now goes through reserve/fill for proper FIFO

**Available endpoints:**
- `/speak-text` - Generate TTS and queue (uses reserve/fill)
- `/reserve` + `/fill` - Manual reserve/fill pattern
- Other control endpoints (pause, resume, status, etc.)

---

### PREVIOUS: HTTP TTS Endpoint COMPLETE

**Added `/speak-text` endpoint to audio manager for TTS without Claude Code.**

```bash
curl -X POST localhost:8881/speak-text \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world", "speed": 1.5, "wait": true}'
```

#### Changes Made (January 15, 2026 - Session 5)

1. **`voice_mode/audio_manager/api.py`**
   - Added `_generate_tts()` - calls Kokoro TTS API directly
   - Added `speak_text()` endpoint with parameters:
     - `text` (required) - text to speak
     - `voice` (optional) - voice name (default: af_sky)
     - `speed` (optional) - 0.25-4.0 (default: 1.0)
     - `project` (optional) - project ID (default: external)
     - `wait` (optional) - block until playback done (default: false)
   - Added route `/speak-text` to `create_app()`

2. **Key Design: No Circular Dependencies**
   - Audio manager calls Kokoro HTTP API directly (not via simple_failover)
   - Uses internal `_service.queue_audio()` (not HTTP to self)
   - Avoids: /speak-text → simple_failover → audio_router → /fill (circular)

#### Test Results - All Pass
- ✅ Basic TTS works
- ✅ Speed parameter works
- ✅ `wait=true` blocks until done (4s for short message)
- ✅ Queue ordering: positions 1, 2, 3 for rapid requests
- ✅ Concurrent with Claude Code converse - no overlap
- ✅ Error handling when Kokoro down: `{"error":"...","spoken":false}`

#### Also: Fixed 17 Failing Tests

Updated tests to use `background=False` and correct mocks for new audio architecture:
- `test_converse_critical_path.py` - 8 tests fixed
- `test_speed_parameter.py` - 6 tests fixed
- `test_wait_repeat_functionality.py` - 2 tests fixed
- `test_endpoint_info_attributes.py` - 2 tests fixed

Test suite: **474 passed, 60 skipped**

#### Next Steps
1. **Test the endpoint** after restarting Claude Code instances
2. **Phase 2: Code cleanup** (~1,100 lines to remove):
   - `voice_mode/audio_player.py` (320 lines) - replaced by audio_manager
   - `voice_mode/dictation_monitor.py` (196 lines) - replaced by audio_manager/hotkey.py
   - `voice_mode/cli.py` + `cli_commands/` (~950 lines) - not needed with HTTP API

#### How to Test After Restart
```bash
# Test 1: Basic TTS
curl -X POST localhost:8881/speak-text \
  -H "Content-Type: application/json" \
  -d '{"text": "Testing after restart"}'

# Test 2: Concurrent with Claude Code - trigger converse from Claude while curl plays

# Test 3: Multi-window - open 2 Claude windows, trigger TTS from both
```

---

### PREVIOUS: Project Announcement for Queued Messages COMPLETE

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
