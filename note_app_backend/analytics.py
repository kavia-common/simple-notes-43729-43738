"""
NoteApp Analytics Module
=======================

This module provides small analytics helpers that can be used by the NoteApp backend
(FastAPI) to compute lightweight metrics such as:

- Counts (e.g., number of notes created)
- Rates (e.g., requests per minute)
- Simple summaries derived from lists of records

Why this exists
---------------
The repository is currently early-stage and may not yet include full application code.
This module is intentionally standalone, pure-Python where possible, and well-documented
so that:

1) Documentation tooling can discover it and generate API docs from docstrings.
2) Future backend code can import and use it.

Design principles
-----------------
- No I/O: functions/classes here do not read/write files or perform network calls.
- Predictable behavior: inputs are validated and errors are explicit.
- Optional analytics dependency: some helpers can optionally use NumPy when installed.

Dependency note (NumPy)
-----------------------
This repository now includes an *analytics dependency* (`numpy`) to support simple
numerical calculations and serve as a discoverable example of analytics usage.

NumPy usage is intentionally optional at runtime:
- If NumPy is available, `compute_average_note_length_numpy(...)` uses it.
- If NumPy is not installed, it raises a clear ImportError with install guidance.

Typical usage
-------------
You can use the `AnalyticsTracker` as an in-memory counter store:

    >>> tracker = AnalyticsTracker(namespace="notes")
    >>> tracker.increment("create_note")
    1
    >>> tracker.increment("create_note", by=2)
    3
    >>> tracker.get("create_note")
    3
    >>> tracker.snapshot()
    {'create_note': 3}

Or compute basic request rate from timestamps:

    >>> from datetime import datetime, timedelta, timezone
    >>> now = datetime.now(tz=timezone.utc)
    >>> timestamps = [now - timedelta(seconds=10), now - timedelta(seconds=5), now]
    >>> round(compute_event_rate_per_minute(timestamps), 2)
    18.0

If you have a collection of note-like dictionaries, you can summarize them:

    >>> notes = [
    ...   {"id": "n1", "title": "A", "content": "Hello"},
    ...   {"id": "n2", "title": "B", "content": "Hello world"},
    ... ]
    >>> summarize_notes(notes)["note_count"]
    2

And (optionally) compute an average using NumPy:

    >>> compute_average_note_length_numpy(notes)
    8.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional


@dataclass
class AnalyticsTracker:
    """
    An in-memory analytics counter tracker.

    This class is intended to be embedded in higher-level services (e.g., FastAPI route
    handlers, service layer classes) to track simple counters such as:

    - number of notes created
    - number of notes deleted
    - number of validation errors
    - number of requests per endpoint

    Important notes
    ---------------
    - This is *not* persistent storage. If the process restarts, counters reset.
    - This is *not* multi-process or multi-node safe. For production analytics, a shared
      store (Redis, Postgres, Prometheus, etc.) would be needed.
    - This class is still useful for:
        * local development
        * tests
        * simple runtime diagnostics
        * documentation examples

    Attributes
    ----------
    namespace:
        A logical grouping label. It is not used in calculations but can help identify
        the counters if multiple trackers exist.
    counters:
        A mutable mapping of counter name to integer value.
    """

    namespace: str = "default"
    counters: MutableMapping[str, int] = field(default_factory=dict)

    def increment(self, key: str, by: int = 1) -> int:
        """
        Increment a named counter and return the new value.

        Parameters
        ----------
        key:
            Counter name (e.g., "create_note", "delete_note", "notes_list").
        by:
            Amount to increment by. Must be a positive integer.

        Returns
        -------
        int
            The updated counter value.

        Raises
        ------
        ValueError
            If `key` is empty or `by` is not a positive integer.
        """
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        if not isinstance(by, int) or by <= 0:
            raise ValueError("by must be a positive integer")

        new_value = int(self.counters.get(key, 0)) + by
        self.counters[key] = new_value
        return new_value

    def get(self, key: str, default: int = 0) -> int:
        """
        Get the current value of a counter.

        Parameters
        ----------
        key:
            Counter name to retrieve.
        default:
            Value to return if the counter does not exist.

        Returns
        -------
        int
            The counter value (or `default` if missing).

        Raises
        ------
        ValueError
            If `key` is empty.
        """
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        return int(self.counters.get(key, default))

    def snapshot(self) -> Dict[str, int]:
        """
        Return a point-in-time copy of all counters.

        Returns
        -------
        dict[str, int]
            A shallow copy of the internal counter mapping.

        Notes
        -----
        A snapshot is useful for:
        - debugging
        - returning metrics in a health/diagnostics endpoint
        - logging a stable view of counters at a moment in time
        """
        return dict(self.counters)


# PUBLIC_INTERFACE
def compute_event_rate_per_minute(
    event_timestamps: Iterable[datetime],
    *,
    now: Optional[datetime] = None,
    window_seconds: int = 60,
) -> float:
    """
    Compute an event rate (events per minute) over a trailing time window.

    This function is commonly useful for simple operational analytics, such as:
    - "requests per minute"
    - "note creations per minute"

    The rate is computed as:

        rate_per_minute = (events_in_window / window_seconds) * 60

    Parameters
    ----------
    event_timestamps:
        An iterable of `datetime` objects representing when events occurred.
        Timestamps may be timezone-aware or naive; however, mixing naive and aware
        datetimes is not supported and will raise an error (Python's default behavior).
    now:
        The reference time used as "current time" for the trailing window.
        If omitted, uses `datetime.now(timezone.utc)` (timezone-aware).
        Tip: passing `now` is helpful for deterministic tests.
    window_seconds:
        Size of the trailing window in seconds. Must be a positive integer.
        Example: `window_seconds=300` computes a 5-minute trailing window.

    Returns
    -------
    float
        The computed rate in events per minute. Returns 0.0 if there are no events.

    Raises
    ------
    ValueError
        If `window_seconds` is not a positive integer.

    Examples
    --------
    >>> from datetime import datetime, timedelta, timezone
    >>> base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    >>> events = [base - timedelta(seconds=59), base - timedelta(seconds=1)]
    >>> compute_event_rate_per_minute(events, now=base, window_seconds=60)
    2.0
    """
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise ValueError("window_seconds must be a positive integer")

    effective_now = now if now is not None else datetime.now(timezone.utc)
    window_start = effective_now.timestamp() - window_seconds

    count = 0
    for ts in event_timestamps:
        # If datetime is naive, timestamp() interprets in local time.
        # We intentionally do not coerce; callers should supply consistent timestamps.
        if ts.timestamp() >= window_start and ts.timestamp() <= effective_now.timestamp():
            count += 1

    return (count / window_seconds) * 60.0


# PUBLIC_INTERFACE
def summarize_notes(
    notes: Iterable[Mapping[str, Any]],
    *,
    content_key: str = "content",
    title_key: str = "title",
    id_key: str = "id",
) -> Dict[str, Any]:
    """
    Summarize a collection of note-like objects.

    This is a general utility that expects an iterable of mappings (e.g., dictionaries)
    and computes basic summary metrics that are commonly useful for UI and operational
    analytics.

    Computed fields
    ---------------
    - note_count: total number of notes
    - notes_with_titles: number of notes where `title_key` is non-empty
    - total_content_chars: sum of lengths of each note's content string
    - average_content_chars: total_content_chars / note_count (0 if no notes)
    - unique_ids: number of unique non-empty IDs found under `id_key`

    Parameters
    ----------
    notes:
        Iterable of mapping-like objects containing note data.
        Example item: {"id": "123", "title": "Shopping", "content": "Milk"}.
    content_key:
        Mapping key holding the note body/content.
    title_key:
        Mapping key holding the note title.
    id_key:
        Mapping key holding the note identifier.

    Returns
    -------
    dict[str, Any]
        A dictionary containing the computed summary metrics.

    Notes
    -----
    - Missing keys are treated as empty strings (for title/content) or `None` (for id).
    - Content/title values are converted to strings if present and not None.

    Examples
    --------
    >>> summarize_notes([{"id": "1", "title": "A", "content": "Hi"}])["average_content_chars"]
    2.0
    """
    note_count = 0
    notes_with_titles = 0
    total_content_chars = 0
    ids_seen = set()

    for note in notes:
        note_count += 1

        raw_title = note.get(title_key)
        title = "" if raw_title is None else str(raw_title)
        if title.strip():
            notes_with_titles += 1

        raw_content = note.get(content_key)
        content = "" if raw_content is None else str(raw_content)
        total_content_chars += len(content)

        raw_id = note.get(id_key)
        if raw_id is not None:
            note_id = str(raw_id).strip()
            if note_id:
                ids_seen.add(note_id)

    average_content_chars = (total_content_chars / note_count) if note_count > 0 else 0.0

    return {
        "note_count": note_count,
        "notes_with_titles": notes_with_titles,
        "total_content_chars": total_content_chars,
        "average_content_chars": float(average_content_chars),
        "unique_ids": len(ids_seen),
    }


# PUBLIC_INTERFACE
def compute_average_note_length_numpy(
    notes: Iterable[Mapping[str, Any]],
    *,
    content_key: str = "content",
) -> float:
    """
    Compute the average note content length (in characters) using NumPy.

    This function exists primarily to provide a *small, concrete example* of using an
    analytics library dependency inside an analytics-related backend module.

    Behavior
    --------
    - Extracts the note content values using `content_key`.
    - Treats missing/None content as empty string.
    - Uses `numpy.mean` to compute the average content length.

    Parameters
    ----------
    notes:
        Iterable of mapping-like objects containing note data.
    content_key:
        Mapping key holding the note body/content.

    Returns
    -------
    float
        Average content length in characters. Returns 0.0 if there are no notes.

    Raises
    ------
    ImportError
        If NumPy is not installed. Install it with: `pip install numpy`.

    Examples
    --------
    >>> notes = [{"content": "Hi"}, {"content": "Hello"}]
    >>> compute_average_note_length_numpy(notes)
    3.5
    """
    try:
        import numpy as np  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "NumPy is required for compute_average_note_length_numpy(). "
            "Install it with `pip install numpy`."
        ) from exc

    lengths = []
    for note in notes:
        raw_content = note.get(content_key)
        content = "" if raw_content is None else str(raw_content)
        lengths.append(len(content))

    if not lengths:
        return 0.0

    return float(np.mean(np.array(lengths, dtype=float)))
