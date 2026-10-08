import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { Line, ReferenceArea } from "recharts";

import { ApiError, api } from "../api/client";
import type { LineDiagnostics, LineReport } from "../api/types";
import { PitchChart } from "../components/PitchChart";
import { useAsync } from "../hooks/useAsync";
import { RAW_VOICE_COLOR, SUSPICIOUS_COLOR } from "../lib/chartColors";
import {
  LOW_VOICING,
  diagnosticRows,
  downloadJson,
  suspiciousWords,
} from "../lib/diagnostics";
import { formatDuration } from "../lib/format";
import { practiceAdvice } from "../lib/practice";
import { difficultyLabel } from "../settings/difficulty";
import {
  clearAdminToken,
  loadAdminToken,
  saveAdminToken,
} from "../settings/adminToken";
import { NotFoundPage } from "./NotFoundPage";

/**
 * Admin diagnostics of a play session (not linked from the app; protected by
 * the admin token until there are user roles).
 */
export function AdminSessionPage() {
  const { sessionId = "" } = useParams();
  const [token, setToken] = useState(loadAdminToken);
  const [rejected, setRejected] = useState(false);

  if (token === null) {
    return (
      <TokenForm
        rejected={rejected}
        onSubmit={(value) => {
          saveAdminToken(value);
          setRejected(false);
          setToken(value);
        }}
      />
    );
  }
  return (
    <SessionDiagnostics
      sessionId={sessionId}
      token={token}
      onRejected={() => {
        clearAdminToken();
        setRejected(true);
        setToken(null);
      }}
    />
  );
}

function TokenForm({
  rejected,
  onSubmit,
}: {
  rejected: boolean;
  onSubmit: (token: string) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <section className="admin">
      <h1>Diagnóstico</h1>
      {rejected && (
        <p role="alert" className="error-box">
          La clave de administrador no es válida.
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) onSubmit(value.trim());
        }}
      >
        <label>
          Clave de administrador{" "}
          <input
            type="password"
            value={value}
            autoComplete="off"
            onChange={(event) => {
              setValue(event.target.value);
            }}
          />
        </label>{" "}
        <button type="submit" className="primary">
          Entrar
        </button>
      </form>
    </section>
  );
}

function SessionDiagnostics({
  sessionId,
  token,
  onRejected,
}: {
  sessionId: string;
  token: string;
  onRejected: () => void;
}) {
  const [state, retry] = useAsync(
    (signal) => api.getSessionResults(sessionId, signal),
    [sessionId],
  );
  const [selected, setSelected] = useState<number | null>(null);

  if (state.status === "loading") return <p className="muted">Cargando…</p>;
  if (state.status === "error") {
    if (state.error instanceof ApiError && state.error.status === 404) {
      return <NotFoundPage />;
    }
    return (
      <div role="alert" className="error-box">
        <p>No se pudo cargar la sesión: {state.error.message}</p>
        <button type="button" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }

  const results = state.data;
  const lineIndex =
    selected ?? results.lines.find((line) => line.sung)?.line_index ?? 0;
  return (
    <section className="admin">
      <header>
        <p className="muted">
          Diagnóstico · {results.player_name} · {difficultyLabel(results.difficulty)} ·{" "}
          {results.status}
        </p>
        <h1>Sesión {results.session_id.slice(0, 8)}</h1>
        <Link to={`/sessions/${results.session_id}/results`}>Ver resultados</Link>
      </header>
      <div className="admin-layout">
        <nav className="admin-lines" aria-label="Versos">
          <ol>
            {results.lines.map((line) => (
              <li key={line.line_index}>
                <button
                  type="button"
                  aria-current={line.line_index === lineIndex ? "true" : undefined}
                  onClick={() => {
                    setSelected(line.line_index);
                  }}
                >
                  <span>{line.line_index + 1}.</span> {line.text}{" "}
                  <span className="muted">{lineScoreLabel(line)}</span>
                </button>
              </li>
            ))}
          </ol>
        </nav>
        <LineDiagnosticsPanel
          key={lineIndex}
          sessionId={sessionId}
          lineIndex={lineIndex}
          token={token}
          onRejected={onRejected}
        />
      </div>
    </section>
  );
}

function lineScoreLabel(line: LineReport): string {
  if (!line.sung) return "—";
  if (line.scorable === false) return "n/p";
  return line.score === null ? "—" : String(Math.round(line.score));
}

function LineDiagnosticsPanel({
  sessionId,
  lineIndex,
  token,
  onRejected,
}: {
  sessionId: string;
  lineIndex: number;
  token: string;
  onRejected: () => void;
}) {
  const [state, retry] = useAsync(
    (signal) => api.getLineDiagnostics(sessionId, lineIndex, token, signal),
    [sessionId, lineIndex, token],
  );
  const unauthorized =
    state.status === "error" &&
    state.error instanceof ApiError &&
    state.error.status === 401;
  useEffect(() => {
    if (unauthorized) onRejected();
  }, [unauthorized, onRejected]);

  if (state.status === "loading") return <p className="muted">Analizando…</p>;
  if (unauthorized) return null;
  if (state.status === "error") {
    return (
      <div role="alert" className="error-box">
        <p>No se pudo analizar el verso: {state.error.message}</p>
        <button type="button" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }
  return <DiagnosticsView diagnostics={state.data} />;
}

export function DiagnosticsView({ diagnostics }: { diagnostics: LineDiagnostics }) {
  const [aligned, setAligned] = useState(false);
  const { analysis } = diagnostics;
  const suspicious = suspiciousWords(diagnostics);

  return (
    <article className="admin-detail">
      <h2>
        Verso {diagnostics.line_index + 1}: {diagnostics.text}
      </h2>
      <p className="muted">
        {formatDuration(diagnostics.start_ms)} – {formatDuration(diagnostics.end_ms)} ·
        estado: {diagnostics.status}
        {analysis !== null &&
          ` · puntaje ${analysis.result.score === null ? "n/p" : String(analysis.result.score)}`}
      </p>

      {suspicious.length > 0 && (
        <p role="status" className="admin-warning">
          Posible desfase de letra: {suspicious.map((word) => word.text).join(", ")}{" "}
          {suspicious.length === 1 ? "tiene" : "tienen"} menos de{" "}
          {Math.round(LOW_VOICING * 100)}% de voz en la original.
        </p>
      )}

      {analysis !== null ? (
        <>
          <ul className="practice-advice">
            {practiceAdvice(analysis).map((advice) => (
              <li key={advice}>{advice}</li>
            ))}
          </ul>
          <label className="practice-toggle">
            <input
              type="checkbox"
              checked={aligned}
              onChange={(event) => {
                setAligned(event.target.checked);
              }}
            />{" "}
            Curva alineada (lo que se puntuó)
          </label>
          <PitchChart
            rows={diagnosticRows(diagnostics, aligned)}
            words={diagnostics.words}
            height={320}
          >
            {suspicious.map((word) => (
              <ReferenceArea
                key={`${word.text}-${String(word.start_ms)}`}
                x1={word.start_ms / 1000}
                x2={word.end_ms / 1000}
                fill={SUSPICIOUS_COLOR}
                fillOpacity={0.12}
                ifOverflow="extendDomain"
              />
            ))}
            {diagnostics.sung_input !== null && (
              <Line
                dataKey="rawVoice"
                name="Sin compensar latencia"
                stroke={RAW_VOICE_COLOR}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                isAnimationActive={false}
              />
            )}
          </PitchChart>
        </>
      ) : (
        <p className="muted">Sin curva cantada para este verso.</p>
      )}

      <h3>Palabras</h3>
      <table className="admin-table">
        <thead>
          <tr>
            <th scope="col">Palabra</th>
            <th scope="col">Inicio</th>
            <th scope="col">Fin</th>
            <th scope="col">Voz en la original</th>
            <th scope="col">Confianza Whisper</th>
          </tr>
        </thead>
        <tbody>
          {diagnostics.word_timing.map((word, index) => (
            <tr
              key={`${word.text}-${String(index)}`}
              className={word.voiced_ratio < LOW_VOICING ? "suspicious" : undefined}
            >
              <th scope="row">{word.text}</th>
              <td>{word.start_ms} ms</td>
              <td>{word.end_ms} ms</td>
              <td>{Math.round(word.voiced_ratio * 100)}%</td>
              <td>
                {word.probability === null
                  ? "—"
                  : `${String(Math.round(word.probability * 100))}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Parámetros</h3>
      <dl className="admin-params">
        <dt>Latencia compensada</dt>
        <dd>{diagnostics.latency_ms} ms</dd>
        <dt>Dificultad</dt>
        <dd>
          {difficultyLabel(diagnostics.difficulty)} (100% hasta{" "}
          {diagnostics.scoring.full_credit_semitones} st, 0 desde{" "}
          {diagnostics.scoring.zero_credit_semitones} st)
        </dd>
        <dt>Desfase máximo / penalización</dt>
        <dd>
          {diagnostics.scoring.max_warp_ms ?? "sin límite"} ms /{" "}
          {diagnostics.scoring.step_penalty_semitones} st por paso
        </dd>
        {analysis !== null && (
          <>
            <dt>Desfase de tiempo / afinación</dt>
            <dd>
              {analysis.timing_offset_ms ?? "—"} ms /{" "}
              {analysis.pitch_offset_semitones ?? "—"} st (octava{" "}
              {analysis.octave_shift} st)
            </dd>
            <dt>Frames de referencia con voz</dt>
            <dd>{analysis.result.voiced_frames}</dd>
          </>
        )}
        <dt>Análisis</dt>
        <dd>
          v{diagnostics.analysis_version} · {diagnostics.pipeline.separator} ·{" "}
          {diagnostics.pipeline.transcriber} · {diagnostics.pipeline.pitch_extractor}
        </dd>
        <dt>Entrada del cliente</dt>
        <dd>
          {diagnostics.sung_input === null
            ? "no guardada"
            : `${String(diagnostics.sung_input.f0_hz.length)} frames cada ${String(diagnostics.sung_input.hop_ms)} ms`}
        </dd>
      </dl>

      <button
        type="button"
        onClick={() => {
          downloadJson(diagnostics);
        }}
      >
        Descargar JSON
      </button>
    </article>
  );
}
