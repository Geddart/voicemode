"""
Thread-safe audio queue with priority and reservation support.

Items are processed in priority order (HIGH > NORMAL > LOW),
and within the same priority, in FIFO order based on reservation time.

Reservation support allows callers to reserve a queue slot before
generating audio, ensuring FIFO ordering even when audio generation
takes variable time across different requests.
"""

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from queue import PriorityQueue, Empty
from typing import Optional, List, Dict


class Priority(IntEnum):
    """Audio queue priority levels."""
    HIGH = 0      # System messages, interrupts (chimes)
    NORMAL = 1    # Regular TTS messages
    LOW = 2       # Background/deferred messages


@dataclass(order=True)
class QueueItem:
    """
    An item in the audio queue.

    Ordering is by (priority, reservation_time) so items with higher priority
    (lower number) are processed first, and within the same priority,
    items reserved earlier are processed first (proper FIFO).
    """
    priority: Priority = field(compare=True)
    reservation_time: float = field(compare=True)  # When slot was reserved
    audio_data: Optional[bytes] = field(compare=False, default=None)  # None = pending
    sample_rate: int = field(compare=False, default=24000)
    project: str = field(compare=False, default="unknown")

    # Unique ID for tracking
    item_id: str = field(compare=False, default_factory=lambda: f"{time.time():.6f}")

    @property
    def is_ready(self) -> bool:
        """Check if audio data is available."""
        return self.audio_data is not None


class AudioQueue:
    """
    Thread-safe audio queue with priority and reservation support.

    Provides:
    - Priority-based ordering (HIGH, NORMAL, LOW)
    - FIFO within same priority based on reservation time
    - Reservation system for gapless playback across windows
    - Queue position and wait time estimates
    - Project-based clearing
    """

    # Average audio duration per byte (rough estimate for 24kHz 16-bit mono)
    # 24000 samples/sec * 2 bytes/sample = 48000 bytes/sec
    BYTES_PER_SECOND = 48000

    # How long to wait for a reserved slot to be filled before skipping
    RESERVATION_TIMEOUT = 30.0  # seconds

    def __init__(self):
        self._lock = threading.Lock()
        self._ready_condition = threading.Condition(self._lock)
        self._items: List[QueueItem] = []
        self._items_by_id: Dict[str, QueueItem] = {}
        self._total_enqueued = 0
        self._total_played = 0

    def reserve(
        self,
        project: str = "unknown",
        priority: Priority = Priority.NORMAL,
    ) -> dict:
        """
        Reserve a queue slot before generating audio.

        Call this BEFORE starting TTS generation to ensure proper
        FIFO ordering across multiple concurrent requests.

        Args:
            project: Project/window name for identification
            priority: Queue priority level

        Returns:
            Dict with item_id to use when filling the slot
        """
        item = QueueItem(
            priority=priority,
            reservation_time=time.time(),
            audio_data=None,  # Pending - will be filled later
            project=project,
        )

        with self._lock:
            self._items.append(item)
            self._items_by_id[item.item_id] = item
            self._total_enqueued += 1
            position = len(self._items)

        return {
            "reserved": True,
            "item_id": item.item_id,
            "position": position,
        }

    def fill(
        self,
        item_id: str,
        audio_data: bytes,
        sample_rate: int = 24000,
    ) -> dict:
        """
        Fill a reserved slot with audio data.

        Args:
            item_id: The item_id from reserve()
            audio_data: Raw audio bytes
            sample_rate: Sample rate in Hz

        Returns:
            Dict with success status
        """
        with self._ready_condition:
            item = self._items_by_id.get(item_id)
            if item is None:
                return {"filled": False, "error": "Item not found or expired"}

            item.audio_data = audio_data
            item.sample_rate = sample_rate

            # Wake up any waiting dequeue calls
            self._ready_condition.notify_all()

        return {"filled": True, "item_id": item_id}

    def enqueue(
        self,
        audio_data: bytes,
        sample_rate: int,
        project: str = "unknown",
        priority: Priority = Priority.NORMAL
    ) -> dict:
        """
        Add audio to the queue immediately (reserve + fill in one call).

        For HIGH priority items (chimes) or when reservation isn't needed.

        Args:
            audio_data: Raw audio bytes
            sample_rate: Sample rate in Hz
            project: Project/window name for identification
            priority: Queue priority level

        Returns:
            Dict with queued=True, position, estimated_wait_ms, item_id
        """
        item = QueueItem(
            priority=priority,
            reservation_time=time.time(),
            audio_data=audio_data,
            sample_rate=sample_rate,
            project=project,
        )

        with self._ready_condition:
            self._items.append(item)
            self._items_by_id[item.item_id] = item
            self._total_enqueued += 1

            # Calculate position (1-indexed)
            position = len(self._items)

            # Estimate wait time based on audio ahead in queue
            wait_ms = self._estimate_wait_ms()

            # Wake up any waiting dequeue calls
            self._ready_condition.notify_all()

        return {
            "queued": True,
            "position": position,
            "estimated_wait_ms": wait_ms,
            "item_id": item.item_id,
        }

    def dequeue(self, timeout: float = 0.1) -> Optional[QueueItem]:
        """
        Get the next ready item from the queue.

        If the next item (by priority/reservation_time) is not ready yet,
        waits up to timeout seconds for it. If it times out and there's
        a ready item behind it, returns that instead.

        Args:
            timeout: How long to wait for the next item to become ready

        Returns:
            QueueItem or None if queue is empty or no items ready
        """
        with self._ready_condition:
            if not self._items:
                return None

            # Sort to find next item by priority and reservation time
            sorted_items = sorted(self._items)

            # Check if the first item is ready
            next_item = sorted_items[0]

            if next_item.is_ready:
                # Ready to play - remove and return
                self._items.remove(next_item)
                del self._items_by_id[next_item.item_id]
                self._total_played += 1
                return next_item

            # Next item is not ready - check if it's timed out
            age = time.time() - next_item.reservation_time
            if age > self.RESERVATION_TIMEOUT:
                # Timed out waiting for audio - remove the reservation
                self._items.remove(next_item)
                del self._items_by_id[next_item.item_id]
                # Try again with remaining items
                if self._items:
                    sorted_items = sorted(self._items)
                    if sorted_items[0].is_ready:
                        item = sorted_items[0]
                        self._items.remove(item)
                        del self._items_by_id[item.item_id]
                        self._total_played += 1
                        return item
                return None

            # Wait for the item to become ready
            self._ready_condition.wait(timeout=timeout)

            # Check again after waiting
            if next_item.item_id in self._items_by_id and next_item.is_ready:
                self._items.remove(next_item)
                del self._items_by_id[next_item.item_id]
                self._total_played += 1
                return next_item

            return None

    def peek(self) -> Optional[QueueItem]:
        """
        Look at the next item without removing it.
        """
        with self._lock:
            if self._items:
                sorted_items = sorted(self._items)
                return sorted_items[0]
        return None

    def clear(self, project: Optional[str] = None) -> int:
        """
        Clear items from the queue.

        Args:
            project: If specified, only clear items from this project.
                    If None, clear all items.

        Returns:
            Number of items cleared
        """
        with self._lock:
            if project is None:
                cleared = len(self._items)
                self._items.clear()
                self._items_by_id.clear()
            else:
                items_to_remove = [i for i in self._items if i.project == project]
                cleared = len(items_to_remove)
                for item in items_to_remove:
                    self._items.remove(item)
                    del self._items_by_id[item.item_id]

        return cleared

    def _estimate_wait_ms(self) -> int:
        """Estimate wait time in milliseconds based on queued audio."""
        total_bytes = 0
        for item in self._items[:-1]:  # Exclude newest
            if item.audio_data:
                total_bytes += len(item.audio_data)
        total_seconds = total_bytes / self.BYTES_PER_SECOND
        return int(total_seconds * 1000)

    @property
    def size(self) -> int:
        """Current queue size."""
        with self._lock:
            return len(self._items)

    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self.size == 0

    def get_status(self) -> dict:
        """Get queue status information."""
        with self._lock:
            pending = sum(1 for i in self._items if not i.is_ready)
            return {
                "queue_length": len(self._items),
                "pending_reservations": pending,
                "total_enqueued": self._total_enqueued,
                "total_played": self._total_played,
                "estimated_wait_ms": self._estimate_wait_ms() if self._items else 0,
            }
