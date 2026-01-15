#!/usr/bin/env python3
"""
View and analyze VoiceMode event logs.

This script provides various ways to visualize the JSONL event logs:
- Session summaries with timing metrics
- Timeline view of events
- Performance statistics
- Error analysis
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional
import statistics


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable."""
    if seconds < 0:
        return f"-{abs(seconds):.2f}s"
    elif seconds < 1:
        return f"{seconds*1000:.0f}ms"
    else:
        return f"{seconds:.2f}s"


def load_events(log_file: Path) -> List[Dict[str, Any]]:
    """Load all events from a log file."""
    events = []
    with open(log_file, 'r') as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def group_by_session(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by session ID."""
    sessions = defaultdict(list)
    for event in events:
        session_id = event.get('session_id', 'no_session')
        sessions[session_id].append(event)
    return sessions


def calculate_session_metrics(session_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate timing metrics for a session."""
    metrics = {}
    events_by_type = defaultdict(list)
    
    # Group by event type
    for event in session_events:
        events_by_type[event['event_type']].append(event)
    
    # Helper to get first event timestamp
    def get_first_ts(event_type: str) -> Optional[datetime]:
        if event_type in events_by_type:
            return parse_timestamp(events_by_type[event_type][0]['timestamp'])
        return None
    
    # Helper to get all events of a type in order
    def get_all_events(event_type: str) -> List[Dict[str, Any]]:
        return sorted(events_by_type.get(event_type, []), 
                     key=lambda e: parse_timestamp(e['timestamp']))
    
    # Calculate key metrics
    # TTFA: TTS_START to TTS_FIRST_AUDIO
    tts_start = get_first_ts('TTS_START')
    tts_first_audio = get_first_ts('TTS_FIRST_AUDIO')
    if tts_start and tts_first_audio:
        metrics['ttfa'] = (tts_first_audio - tts_start).total_seconds()
    
    # TTS Generation: TTS_START to TTS_PLAYBACK_END (total time to generate all audio)
    tts_playback_start = get_first_ts('TTS_PLAYBACK_START')
    tts_playback_end = get_first_ts('TTS_PLAYBACK_END')
    if tts_start and tts_playback_end:
        metrics['tts_generation'] = (tts_playback_end - tts_start).total_seconds()
    
    # TTS Playback: TTS_PLAYBACK_START to TTS_PLAYBACK_END
    tts_playback_end = get_first_ts('TTS_PLAYBACK_END')
    if tts_playback_start and tts_playback_end:
        metrics['tts_playback'] = (tts_playback_end - tts_playback_start).total_seconds()
    
    # Recording: RECORDING_START to RECORDING_END
    rec_start = get_first_ts('RECORDING_START')
    rec_end = get_first_ts('RECORDING_END')
    if rec_start and rec_end:
        metrics['recording'] = (rec_end - rec_start).total_seconds()
    
    # Response time: RECORDING_END to next TTS_PLAYBACK_START
    # This is the user-perceived response time
    if rec_end and len(events_by_type.get('TTS_PLAYBACK_START', [])) > 1:
        # Find the TTS playback that happens after recording ends
        for event in events_by_type['TTS_PLAYBACK_START']:
            event_ts = parse_timestamp(event['timestamp'])
            if event_ts > rec_end:
                metrics['response_time'] = (event_ts - rec_end).total_seconds()
                break
    
    # Total session time
    if session_events:
        first_ts = parse_timestamp(session_events[0]['timestamp'])
        last_ts = parse_timestamp(session_events[-1]['timestamp'])
        metrics['total_duration'] = (last_ts - first_ts).total_seconds()
    
    # AI thinking time (between tool requests)
    tool_ends = get_all_events('TOOL_REQUEST_END')
    tool_starts = get_all_events('TOOL_REQUEST_START')
    
    if len(tool_ends) > 0 and len(tool_starts) > 1:
        # Find pairs of tool end -> next tool start
        thinking_times = []
        for i, end_event in enumerate(tool_ends):
            end_ts = parse_timestamp(end_event['timestamp'])
            # Find next tool start after this end
            for start_event in tool_starts:
                start_ts = parse_timestamp(start_event['timestamp'])
                if start_ts > end_ts:
                    thinking_time = (start_ts - end_ts).total_seconds()
                    thinking_times.append(thinking_time)
                    break
        
        if thinking_times:
            metrics['ai_thinking_times'] = thinking_times
            metrics['ai_thinking_avg'] = sum(thinking_times) / len(thinking_times)
            metrics['ai_thinking_min'] = min(thinking_times)
            metrics['ai_thinking_max'] = max(thinking_times)
    
    return metrics


def print_session_summary(session_id: str, events: List[Dict[str, Any]]):
    """Print a summary of a session."""
    print(f"\n{'='*60}")
    print(f"Session: {session_id}")
    print(f"{'='*60}")
    
    if not events:
        print("No events")
        return
    
    # Basic info
    start_time = parse_timestamp(events[0]['timestamp'])
    end_time = parse_timestamp(events[-1]['timestamp'])
    duration = (end_time - start_time).total_seconds()
    
    print(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {format_duration(duration)}")
    print(f"Events: {len(events)}")
    
    # Check for time since last session event
    for event in events:
        if event['event_type'] == 'TIME_SINCE_LAST_SESSION':
            time_since = event['data'].get('seconds', 0)
            print(f"Time since last session: {format_duration(time_since)} (AI thinking time)")
    
    # Calculate metrics
    metrics = calculate_session_metrics(events)
    
    if metrics:
        print(f"\nTiming Metrics:")
        print(f"  TTFA (Time to First Audio): {format_duration(metrics.get('ttfa', 0))}")
        print(f"  TTS Generation: {format_duration(metrics.get('tts_generation', 0))}")
        print(f"  TTS Playback: {format_duration(metrics.get('tts_playback', 0))}")
        print(f"  Recording: {format_duration(metrics.get('recording', 0))}")
        print(f"  Response Time: {format_duration(metrics.get('response_time', 0))}")
        
        # AI thinking time
        if 'ai_thinking_avg' in metrics:
            print(f"\nAI Thinking Time:")
            print(f"  Average: {format_duration(metrics['ai_thinking_avg'])}")
            print(f"  Min: {format_duration(metrics['ai_thinking_min'])}")
            print(f"  Max: {format_duration(metrics['ai_thinking_max'])}")
            if len(metrics['ai_thinking_times']) > 1:
                print(f"  Samples: {len(metrics['ai_thinking_times'])}")
    
    # Show conversation content
    for event in events:
        if event['event_type'] == 'TTS_START':
            msg = event['data'].get('message', '')[:100]
            print(f"\nTTS: \"{msg}{'...' if len(msg) == 100 else ''}\"")



def print_timeline(events: List[Dict[str, Any]]):
    """Print events in timeline format."""
    if not events:
        print("No events")
        return
    
    start_time = parse_timestamp(events[0]['timestamp'])
    
    print(f"\nTimeline (starting at {start_time.strftime('%H:%M:%S.%f')[:-3]}):")
    print(f"{'Time':>8} {'Event Type':25} {'Details'}")
    print("-" * 70)
    
    for event in events:
        event_time = parse_timestamp(event['timestamp'])
        elapsed = (event_time - start_time).total_seconds()
        
        # Format details based on event type
        details = ""
        if event['event_type'] == 'TTS_START':
            voice = event['data'].get('voice', '')
            msg = event['data'].get('message', '')[:40]
            details = f"voice={voice}, msg=\"{msg}...\""
        elif event['event_type'] == 'RECORDING_END':
            duration = event['data'].get('duration', 0)
            details = f"duration={format_duration(duration)}"
        elif event['event_type'] == 'TOOL_REQUEST_START':
            tool = event['data'].get('tool_name', '')
            wait = event['data'].get('wait_for_response', '')
            details = f"tool={tool}, wait_for_response={wait}"
        elif event['event_type'] == 'TOOL_REQUEST_END':
            tool = event['data'].get('tool_name', '')
            success = event['data'].get('success', True)
            details = f"tool={tool}, success={success}"
        
        print(f"{elapsed:>7.3f}s {event['event_type']:25} {details}")


def calculate_ai_thinking_times(all_events: List[Dict[str, Any]]) -> List[float]:
    """Calculate AI thinking times from all events chronologically."""
    thinking_times = []
    
    # Sort all events by timestamp
    sorted_events = sorted(all_events, key=lambda e: parse_timestamp(e['timestamp']))
    
    # Find tool request end -> next tool request start pairs
    last_tool_end = None
    for event in sorted_events:
        if event['event_type'] == 'TOOL_REQUEST_END':
            last_tool_end = parse_timestamp(event['timestamp'])
        elif event['event_type'] == 'TOOL_REQUEST_START' and last_tool_end:
            tool_start = parse_timestamp(event['timestamp'])
            thinking_time = (tool_start - last_tool_end).total_seconds()
            thinking_times.append(thinking_time)
            # Don't reset last_tool_end, as we want to track all gaps
    
    return thinking_times


def print_statistics(all_sessions: Dict[str, List[Dict[str, Any]]]):
    """Print aggregate statistics across all sessions."""
    all_metrics = []
    all_events = []
    
    for session_id, events in all_sessions.items():
        all_events.extend(events)
        if session_id != 'no_session':
            metrics = calculate_session_metrics(events)
            if metrics:
                all_metrics.append(metrics)
    
    if not all_metrics:
        print("\nNo complete sessions with metrics found")
        return
    
    print(f"\n{'='*60}")
    print(f"AGGREGATE STATISTICS ({len(all_metrics)} sessions)")
    print(f"{'='*60}")
    
    # Calculate aggregates for each metric
    metric_names = ['ttfa', 'tts_generation', 'tts_playback', 'recording', 'response_time', 'ai_thinking_avg']
    
    for metric_name in metric_names:
        values = [m.get(metric_name, 0) for m in all_metrics if metric_name in m]
        if values:
            avg = statistics.mean(values)
            min_val = min(values)
            max_val = max(values)
            
            display_name = metric_name.replace('_', ' ').title()
            print(f"\n{display_name}:")
            print(f"  Average: {format_duration(avg)}")
            print(f"  Min: {format_duration(min_val)}")
            print(f"  Max: {format_duration(max_val)}")
            
            if len(values) > 1:
                median = statistics.median(values)
                print(f"  Median: {format_duration(median)}")
    
    # Calculate AI thinking times from all events
    thinking_times = calculate_ai_thinking_times(all_events)
    if thinking_times:
        print(f"\nAI Thinking Time (from all events):")
        print(f"  Average: {format_duration(statistics.mean(thinking_times))}")
        print(f"  Min: {format_duration(min(thinking_times))}")
        print(f"  Max: {format_duration(max(thinking_times))}")
        if len(thinking_times) > 1:
            print(f"  Median: {format_duration(statistics.median(thinking_times))}")
        print(f"  Samples: {len(thinking_times)}")


def main():
    parser = argparse.ArgumentParser(description='View and analyze VoiceMode event logs')
    parser.add_argument('log_file', nargs='?', help='Log file to analyze (default: latest in ~/voicemode_logs)')
    parser.add_argument('--sessions', '-s', action='store_true', help='Show session summaries')
    parser.add_argument('--timeline', '-t', action='store_true', help='Show timeline view')
    parser.add_argument('--statistics', '-S', action='store_true', help='Show aggregate statistics')
    parser.add_argument('--session-id', help='Show specific session')
    parser.add_argument('--last', '-l', type=int, help='Show last N sessions')
    
    args = parser.parse_args()
    
    # Find log file
    if args.log_file:
        log_file = Path(args.log_file)
    else:
        # Default to latest log in ~/voicemode_logs
        log_dir = Path.home() / "voicemode_logs"
        if not log_dir.exists():
            print(f"Log directory not found: {log_dir}")
            sys.exit(1)
        
        log_files = sorted(log_dir.glob("*.jsonl"))
        if not log_files:
            print(f"No log files found in {log_dir}")
            sys.exit(1)
        
        log_file = log_files[-1]
        print(f"Using latest log file: {log_file}")
    
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        sys.exit(1)
    
    # Load events
    events = load_events(log_file)
    print(f"Loaded {len(events)} events")
    
    # Group by session
    sessions = group_by_session(events)
    
    # Default view if no options specified
    if not any([args.sessions, args.timeline, args.statistics, args.session_id]):
        args.sessions = True
    
    # Handle different views
    if args.session_id:
        if args.session_id in sessions:
            print_session_summary(args.session_id, sessions[args.session_id])
            if args.timeline:
                print_timeline(sessions[args.session_id])
        else:
            print(f"Session not found: {args.session_id}")
            print(f"Available sessions: {', '.join(sessions.keys())}")
    
    elif args.sessions:
        # Sort sessions by first event timestamp
        sorted_sessions = sorted(
            [(sid, events) for sid, events in sessions.items() if sid != 'no_session'],
            key=lambda x: parse_timestamp(x[1][0]['timestamp']) if x[1] else datetime.min
        )
        
        # Apply --last filter
        if args.last:
            sorted_sessions = sorted_sessions[-args.last:]
        
        for session_id, session_events in sorted_sessions:
            print_session_summary(session_id, session_events)
    
    elif args.timeline:
        print_timeline(events)
    
    if args.statistics:
        print_statistics(sessions)


if __name__ == "__main__":
    main()