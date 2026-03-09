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
    In-memory analytics counter tracker (process-local).

    This class stores named integer counters in a mutable mapping and is intended for
    *lightweight instrumentation* inside a backend (for example, FastAPI route handlers
    or a service layer).

    Typical counters include:
    - number of notes created / deleted
    - number of requests per endpoint
    - number of validation errors
    - any other discrete event counts you want to observe during runtime

    Important limitations
    ---------------------
    - **Not persistent**: counters reset when the Python process restarts.
    - **Not multi-process safe**: if you run multiple workers (e.g., gunicorn/uvicorn
      workers), each worker has its own tracker instance/state.
    - **Not a metrics backend**: for production-grade analytics, use a shared store or a
      metrics system (Redis/Postgres/Prometheus/OpenTelemetry, etc.).

    Attributes
    ----------
    namespace:
        Logical grouping label for the tracker. This module does not interpret the value,
        but it can be helpful when logging or when multiple trackers exist.
    counters:
        Mutable mapping of counter name to integer value.

    Examples
    --------
    >>> tracker = AnalyticsTracker(namespace="notes")
    >>> tracker.increment("create_note")
    1
    >>> tracker.increment("create_note", by=2)
    3
    >>> tracker.get("create_note")
    3
    >>> tracker.snapshot()
    {'create_note': 3}
    """

    namespace: str = "default"
    counters: MutableMapping[str, int] = field(default_factory=dict)

    def increment(self, key: str, by: int = 1) -> int:
        """
        Increment a named counter and return the updated value.

        Parameters
        ----------
        key:
            Counter name (for example: ``"create_note"``, ``"delete_note"``,
            ``"notes_list"``). Must be a non-empty string.
        by:
            Amount to increment by. Must be a positive integer (>= 1).

        Returns
        -------
        int
            The updated counter value after incrementing.

        Raises
        ------
        ValueError
            If ``key`` is empty/blank, or if ``by`` is not a positive integer.

        Notes
        -----
        This method mutates the internal ``counters`` mapping.
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
            Counter name to retrieve. Must be a non-empty string.
        default:
            Value to return if the counter does not exist.

        Returns
        -------
        int
            Current counter value (or ``default`` if missing).

        Raises
        ------
        ValueError
            If ``key`` is empty/blank.
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
            A shallow copy of the internal counter mapping (safe to modify by callers).

        Usage
        -----
        This is useful for diagnostics endpoints, logs, or quick debugging:

        >>> tracker = AnalyticsTracker()
        >>> tracker.increment("x")
        1
        >>> tracker.snapshot()
        {'x': 1}
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
    Compute an event rate in **events per minute** over a trailing time window.

    This is a small utility for operational-style analytics such as:
    - requests per minute
    - note creations per minute
    - background job executions per minute

    The function counts how many timestamps fall within the trailing window:

    - Window end: ``now`` (defaults to current UTC time)
    - Window start: ``now - window_seconds``

    Then computes::

        rate_per_minute = (events_in_window / window_seconds) * 60

    Parameters
    ----------
    event_timestamps:
        Iterable of :class:`datetime.datetime` values representing when events occurred.
        The iterable is consumed once.

        Timezone guidance:
        - You may pass timezone-aware or naive datetimes.
        - **Do not mix** naive and timezone-aware datetimes across ``event_timestamps``
          and ``now``; Python will raise when comparing/operating on mixed types in many
          contexts.
    now:
        Reference time considered as "current time" for the trailing window. If omitted,
        uses ``datetime.now(timezone.utc)``.

        Passing an explicit value is recommended in tests to make results deterministic.
    window_seconds:
        Size of the trailing window in seconds. Must be a positive integer.

    Returns
    -------
    float
        The computed rate as events per minute. Returns ``0.0`` when the input contains
        no events within the window (including the case where ``event_timestamps`` is
        empty).

    Raises
    ------
    ValueError
        If ``window_seconds`` is not a positive integer.

    Examples
    --------
    Deterministic computation (recommended for tests):

    >>> from datetime import datetime, timedelta, timezone
    >>> base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    >>> events = [base - timedelta(seconds=59), base - timedelta(seconds=1)]
    >>> compute_event_rate_per_minute(events, now=base, window_seconds=60)
    2.0

    Empty input yields 0.0:

    >>> compute_event_rate_per_minute([], now=base, window_seconds=60)
    0.0
    """
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise ValueError("window_seconds must be a positive integer")

    effective_now = now if now is not None else datetime.now(timezone.utc)
    window_start = effective_now.timestamp() - window_seconds

    count = 0
    effective_now_ts = effective_now.timestamp()
    for ts in event_timestamps:
        # If datetime is naive, timestamp() interprets in local time.
        # We intentionally do not coerce; callers should supply consistent timestamps.
        ts_value = ts.timestamp()
        if window_start <= ts_value <= effective_now_ts:
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
    Summarize a collection of note-like mappings into simple aggregate metrics.

    This function is intentionally *schema-light*: it expects an iterable of mapping-like
    objects (most commonly dictionaries) and extracts ``id``, ``title``, and ``content``
    fields using the configured keys.

    It is useful for:
    - lightweight analytics displayed in an admin/diagnostics panel
    - generating quick summaries for tests or debugging
    - producing derived metrics without additional dependencies

    Computed fields
    ---------------
    The returned dictionary contains:

    - ``note_count``:
        Total number of notes encountered.
    - ``notes_with_titles``:
        Count of notes whose title (``title_key``) is a non-empty string after stripping.
    - ``total_content_chars``:
        Sum of ``len(content)`` across all notes.
    - ``average_content_chars``:
        Average content length as ``total_content_chars / note_count``; ``0.0`` when
        there are no notes.
    - ``unique_ids``:
        Number of unique, non-empty IDs found under ``id_key``.

    Parameters
    ----------
    notes:
        Iterable of mapping-like objects containing note data.

        Minimal example item::

            {"id": "123", "title": "Shopping", "content": "Milk"}
    content_key:
        Key that holds the note body/content.
    title_key:
        Key that holds the note title.
    id_key:
        Key that holds the note identifier.

    Returns
    -------
    dict[str, Any]
        Summary metrics described above.

    Notes
    -----
    - Missing keys are treated as:
      - empty string for title/content (so they contribute 0 chars / no title)
      - ``None`` for id (so it is ignored)
    - Non-string values for title/content/id are coerced to strings when present.

    Examples
    --------
    >>> notes = [
    ...     {"id": "n1", "title": "A", "content": "Hello"},
    ...     {"id": "n2", "title": "", "content": "World"},
    ...     {"id": "n2", "title": None, "content": None},
    ... ]
    >>> summary = summarize_notes(notes)
    >>> summary["note_count"]
    3
    >>> summary["notes_with_titles"]
    1
    >>> summary["unique_ids"]
    2
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
    Compute average note content length (characters) using NumPy.

    This helper demonstrates how an analytics-oriented module may optionally rely on a
    third-party numerical library for computation. In this repository it is primarily a
    *documentation-friendly example* of an optional dependency.

    Behavior
    --------
    - Extracts each note's content using ``content_key``.
    - Treats missing or ``None`` content as an empty string.
    - Computes the mean of the content lengths using ``numpy.mean``.

    Parameters
    ----------
    notes:
        Iterable of mapping-like objects containing note data.
        Each item is expected to support ``.get(content_key)``.
    content_key:
        Key holding the note body/content.

    Returns
    -------
    float
        Average content length in characters.

        Returns ``0.0`` if the iterable contains no notes.

    Raises
    ------
    ImportError
        If NumPy is not installed in the runtime environment. Install it with::

            pip install numpy

    Examples
    --------
    >>> notes = [{"content": "Hi"}, {"content": "Hello"}, {"content": None}]
    >>> compute_average_note_length_numpy(notes)
    2.3333333333333335
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
