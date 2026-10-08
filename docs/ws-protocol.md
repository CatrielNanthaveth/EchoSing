# Play session protocol

How a client sings a song and gets each line scored in real time. Messages are JSON
text frames. Schemas live in `backend/app/schemas/sessions.py`.

## 1. Start a session (REST)

```http
POST /sessions
{"song_id": "<uuid>", "player_name": "Ana", "latency_offset_ms": 120}
```

`latency_offset_ms` is the audio latency measured by the client's calibration
(positive: the voice arrives late, e.g. Bluetooth headphones). Range -500..1000.

```json
201 {"session_id": "<uuid>", "song_id": "<uuid>", "analysis_id": "<uuid>",
     "analysis_version": 1, "line_count": 64, "player_name": "Ana",
     "latency_offset_ms": 120}
```

The session is bound to `analysis_id`: lyrics and timings come from
`GET /songs/{song_id}`, which returns the same `analysis_id` while no newer version
is published. `404` if the song is not playable.

## 2. Connect

```
WS /ws/sessions/{session_id}
```

| Close code | Meaning |
|---|---|
| `4404` | The session does not exist |
| `4409` | The session is already finished |

On success the server sends:

```json
{"type": "ready", "session_id": "<uuid>", "analysis_id": "<uuid>",
 "line_count": 64, "scored_lines": []}
```

`scored_lines` lists the lines already scored: a client can reconnect after a network
drop and continue where it left off.

## 3. Send each line when it ends

```json
{"type": "line_pitch", "line_index": 13, "hop_ms": 11.61, "f0_hz": [0, 0, 146.8, 147.1, ...]}
```

- `f0_hz`: the player's pitch per frame in Hz, **starting at the line's `start_ms`**
  (playback time), `0` where there is no voice. Values 0..5000.
- Send frames until `end_ms + 300 ms`: the server shifts the curve by the session
  latency and drops anything past the end of the line.
- `hop_ms`: time between frames, 5..50 (e.g. 512 samples at 44.1 kHz = 11.61 ms).
- At most 6000 frames per message.

Reply:

```json
{"type": "line_score", "line_index": 13, "scorable": true,
 "score": 87.5, "accuracy": 0.82, "hit": true, "streak": 4}
```

- `score` 0..100 and `accuracy` 0..1 (fraction of in-tune frames).
- `hit`: score >= 60; `streak`: consecutive hits ending at this line (a line that was
  not sung ends it; lines that are not scorable are skipped).
- `scorable: false` (with `score`/`accuracy` null) for lines with almost no sung
  reference, e.g. spoken passages: they neither count nor break streaks.

## 4. Finish

When the song ends:

```json
{"type": "finish"}
```

The server stores the totals, replies and closes the connection (code 1000):

```json
{"type": "session_summary", "total_score": 78.4, "accuracy": 0.61,
 "best_streak": 12, "scored_lines": 63, "hit_lines": 50}
```

Lines that were never sent count as 0 (otherwise singing one line perfectly would
give a perfect total). `total_score`/`accuracy` are null if the song has nothing
scorable. Reconnecting to a finished session closes with `4409`.

## 5. Results (REST)

```http
GET /sessions/{session_id}/results
```

Returns the session (`status`, `started_at`, `finished_at`), its `totals` (same fields
as `session_summary`) and one entry per line: `line_index`, `text`, `sung`,
`scorable`, `score`, `accuracy`, `hit`. While the session is active, totals cover the
lines sung so far and unsung lines have null results; once finished, unsung lines
score 0 (`sung: false`). `404` if the session does not exist.

## 6. Errors

Errors never close the connection:

```json
{"type": "error", "code": "line_already_scored", "detail": "Line 13 was already scored"}
```

| `code` | When |
|---|---|
| `invalid_message` | Malformed JSON, unknown `type` or values out of range |
| `unknown_line` | `line_index` is not a line of the analysis |
| `line_already_scored` | The line was already scored in this session |

## Scoring in short

Pitch is compared in semitones, ignoring whole-octave differences; DTW tolerates
late entries and small rhythm variations (up to 200 ms). Full credit within half a
semitone, none from 2 semitones. Details: `backend/README.md`, "Scoring engine".
