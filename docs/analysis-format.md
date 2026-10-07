# Song analysis format — version 1

The **song analysis** is the contract between the ingestion pipeline (producer), the
catalog API, the scoring engine and the web client (consumers). It holds the synced
lyrics and the reference pitch of the isolated vocals.

- Stored as JSONB in `song_analyses.data`, with the version in
  `song_analyses.format_version`.
- Defined in code by `app/schemas/analysis.py` (`SongAnalysisData`). The code is
  the source of truth; this document explains the reasoning.
- A song can have several analysis versions (re-processing). Play sessions point to
  the exact version they were scored against.
- Reference example: [backend/tests/fixtures/analysis_v1.json](../backend/tests/fixtures/analysis_v1.json).

## Structure

```jsonc
{
  "format_version": 1,
  "duration_ms": 3000,                  // song duration
  "pipeline": {                         // how it was produced (reproducibility)
    "separator": "htdemucs",
    "transcriber": "whisper-large-v3-turbo",
    "pitch_extractor": "torchcrepe-full",
    "language": "en"                    // detected or forced; may be null
  },
  "lines": [                            // the unit that gets scored
    {
      "index": 0,                       // contiguous 0..n-1
      "start_ms": 200,
      "end_ms": 900,                    // exclusive
      "text": "Hello darkness, my",
      "words": [
        { "text": "Hello", "start_ms": 200, "end_ms": 450, "probability": 0.93 }
        // ...
      ]
    }
  ],
  "pitch": {                            // ONE curve for the whole song
    "hop_ms": 10,                       // frame i is centered at i * hop_ms
    "midi":       [null, 57.02, 57.05, 59.98],   // fractional MIDI, 0.01 steps
    "confidence": [   3,    41,    88,    95]    // voicing confidence 0..100
  }
}
```

## Design decisions

### Times are integer milliseconds
No floating-point drift when comparing or shifting times (e.g. by the measured
Bluetooth latency).

### One global pitch curve, sliced per line
Lines only store their time range; the reference pitch of a line is
`pitch.slice_ms(line.start_ms, line.end_ms)` (`SongAnalysisData.line_pitch`).
Nothing is duplicated, re-segmenting lyrics does not require re-extracting pitch,
and a latency shift can cross line boundaries.

### Pitch in fractional MIDI note numbers
`midi = 69 + 12 · log2(f / 440 Hz)`, so 69.00 = A4 = 440 Hz and 1.00 = 1 semitone =
100 cents.

- CREPE itself works in cents (360 bins of 20 cents) and converts to Hz at the end,
  so MIDI is its native log-frequency scale with another origin; nothing is lost
  beyond rounding.
- Rounding to 0.01 means at most **0.5 cents** of error, uniformly across the range.
  CREPE's own error on separated vocals is in the order of 10–20 cents, and scoring
  tolerances are around 50–100 cents.
- Scoring compares pitch in cents: the difference is simply `100 · Δmidi`.
- Clients send Hz; the server converts.

### Confidence is kept; voicing is decided when reading
Every frame stores its estimate and its confidence (0–100). Which frames count as
singing is decided by the consumer:

```python
pitch.to_numpy(min_confidence=50)   # NaN where confidence < 50 or no estimate
pitch.confidence_weights()          # 0..1, for confidence-weighted scoring
```

Changing the voicing threshold therefore never requires re-running the GPU
pipeline. `null` is reserved for frames with no estimate at all (JSON has no NaN).

## Invariants (enforced by validation)

- `end_ms > start_ms` for every word and line.
- Words are sorted, do not overlap and lie within their line.
- Lines are sorted, do not overlap, have contiguous indexes from 0 and end within
  `duration_ms`.
- `midi` and `confidence` have the same length; MIDI values are within [0, 127]
  and confidence within [0, 100].
- Unknown fields are rejected.

## Size

About 24,000 frames for a 4-minute song: roughly 200 KB of JSON, compressed by
PostgreSQL (TOAST) on disk. Endpoints that only need lyrics should select
`data->'lines'` instead of loading the whole document.

## Evolving the format

Breaking changes create `format_version = 2` with its own models. `parse_analysis`
dispatches on the version and raises `UnsupportedFormatError` for unknown ones, so
old analyses keep working until they are re-processed.
