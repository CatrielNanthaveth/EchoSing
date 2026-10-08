import type {
  LineAnalysis,
  LineDiagnostics,
  LinePractice,
  LyricLine,
  SongDetail,
  SongPage,
  SongSummary,
} from "../api/types";

export function songSummary(overrides: Partial<SongSummary> = {}): SongSummary {
  return {
    id: "song-1",
    title: "Chachacha",
    artist: "Josean Log",
    language: "es",
    duration_ms: 215_000,
    line_count: 37,
    reprocessing: false,
    ...overrides,
  };
}

export function songPage(
  items: SongSummary[],
  overrides: Partial<SongPage> = {},
): SongPage {
  return { items, total: items.length, limit: 20, offset: 0, ...overrides };
}

/** A line whose words split its time evenly. */
export function lyricLine(
  index: number,
  startMs: number,
  endMs: number,
  text: string,
): LyricLine {
  const words = text.split(" ");
  const step = (endMs - startMs) / words.length;
  return {
    index,
    start_ms: startMs,
    end_ms: endMs,
    text,
    words: words.map((word, i) => ({
      text: word,
      start_ms: Math.round(startMs + i * step),
      end_ms: Math.round(startMs + (i + 1) * step),
    })),
  };
}

export function songDetail(overrides: Partial<SongDetail> = {}): SongDetail {
  const lines = [
    lyricLine(0, 5000, 7000, "Hola mundo"),
    lyricLine(1, 8000, 10000, "Segunda línea"),
    lyricLine(2, 10000, 12000, "Tercera línea"),
  ];
  return {
    id: "song-1",
    title: "Chachacha",
    artist: "Josean Log",
    language: "es",
    duration_ms: 60_000,
    line_count: lines.length,
    reprocessing: false,
    analysis_id: "analysis-1",
    analysis_version: 1,
    lines,
    ...overrides,
  };
}

/** A perfectly sung 0.2 s line: reference A3 then B3, 20 ms frames. */
export function lineAnalysis(overrides: Partial<LineAnalysis> = {}): LineAnalysis {
  const reference = [57, 57, 57, 57, 57, 59, 59, 59, 59, null];
  return {
    result: { scorable: true, score: 100, accuracy: 1, hit: true, voiced_frames: 9 },
    hop_ms: 20,
    reference_midi: reference,
    reference_weight: reference.map(() => 0.95),
    sung_midi: reference,
    aligned_midi: reference,
    credit: reference.map((value) => (value === null ? null : 1)),
    alignment_path: reference.map((_, i) => [i, i]),
    octave_shift: 0,
    timing_offset_ms: 0,
    pitch_offset_semitones: 0,
    ...overrides,
  };
}

export function linePractice(overrides: Partial<LinePractice> = {}): LinePractice {
  return {
    session_id: "session-1",
    line_index: 0,
    text: "Hola mundo",
    start_ms: 5000,
    end_ms: 5200,
    difficulty: "normal",
    words: [
      { text: "Hola", start_ms: 0, end_ms: 100 },
      { text: "mundo", start_ms: 100, end_ms: 200 },
    ],
    status: "analyzed",
    analysis: lineAnalysis(),
    ...overrides,
  };
}

export function lineDiagnostics(
  overrides: Partial<LineDiagnostics> = {},
): LineDiagnostics {
  return {
    ...linePractice(),
    latency_ms: 40,
    scoring: {
      scoring_hop_ms: 20,
      min_reference_confidence: 50,
      min_voiced_ms: 200,
      full_credit_semitones: 0.75,
      zero_credit_semitones: 2.5,
      max_error_semitones: 6,
      max_gap_ms: 100,
      octave_invariant: true,
      max_warp_ms: 200,
      step_penalty_semitones: 2,
      hit_threshold: 60,
    },
    analysis_version: 2,
    pipeline: {
      separator: "htdemucs",
      transcriber: "whisper-large-v3-turbo",
      pitch_extractor: "torchcrepe-full",
      language: "es",
    },
    reference: { hop_ms: 10, midi: [57, 57], confidence: [95, 95] },
    // 220 Hz = A3 (57), sent every 20 ms like the analysis frames.
    sung_input: { hop_ms: 20, f0_hz: [0, 220, 220, 220, 220, 220, 220, 220, 220, 220] },
    word_timing: [
      { text: "Hola", start_ms: 0, end_ms: 100, voiced_ratio: 1, probability: 0.93 },
      {
        text: "mundo",
        start_ms: 100,
        end_ms: 200,
        voiced_ratio: 0.2,
        probability: null,
      },
    ],
    ...overrides,
  };
}
