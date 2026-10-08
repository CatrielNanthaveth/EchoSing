import { useState } from "react";

import type { VoiceFrame } from "../audio/frameAnalyzer";
import type { Microphone } from "../audio/microphone";
import { microphoneErrorMessage } from "../audio/microphone";
import { micTestAdvice, micTestStats, type MicTestStats } from "../lib/micTest";

/** Each step of the test, in order. */
const MIC_TEST_STEPS = [
  { id: "sustained", seconds: 4, prompt: "Sostené una nota cómoda: “aaaaa…”" },
  { id: "phrase", seconds: 6, prompt: "Ahora cantá una frase de una canción" },
] as const;

type StepId = (typeof MIC_TEST_STEPS)[number]["id"];

type Phase =
  | { name: "idle" }
  | { name: "recording"; step: number }
  | { name: "done"; stats: Record<StepId, MicTestStats> }
  | { name: "error"; message: string };

function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

/**
 * Microphone test: records the player singing and reports how much of the
 * voice is detected and why the rest is dropped (too quiet or not periodic).
 */
export function MicTest({
  getMicrophone,
}: {
  getMicrophone: () => Promise<Microphone>;
}) {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [copied, setCopied] = useState(false);

  const run = async () => {
    setCopied(false);
    try {
      const microphone = await getMicrophone();
      const recorded: Partial<Record<StepId, MicTestStats>> = {};
      for (const [index, step] of MIC_TEST_STEPS.entries()) {
        setPhase({ name: "recording", step: index });
        const frames: VoiceFrame[] = [];
        const stop = microphone.subscribe((frame) => frames.push(frame));
        await new Promise((resolve) => setTimeout(resolve, step.seconds * 1000));
        stop();
        recorded[step.id] = micTestStats(frames);
      }
      setPhase({
        name: "done",
        stats: recorded as Record<StepId, MicTestStats>,
      });
    } catch (error) {
      setPhase({ name: "error", message: microphoneErrorMessage(error) });
    }
  };

  return (
    <section className="mic-test" aria-labelledby="mic-test-title">
      <h2 id="mic-test-title">Prueba de micrófono</h2>
      <p className="muted">
        Comprobá que se detecte bien tu voz. Usá el mismo micrófono y la misma distancia
        con la que vas a cantar.
      </p>

      {phase.name === "recording" ? (
        <p className="mic-test-prompt" role="status">
          {MIC_TEST_STEPS[phase.step]?.prompt} ({MIC_TEST_STEPS[phase.step]?.seconds} s)
        </p>
      ) : (
        <button type="button" onClick={() => void run()}>
          {phase.name === "done" ? "Repetir prueba" : "Probar micrófono"}
        </button>
      )}

      {phase.name === "error" && (
        <p role="alert" className="error-box">
          {phase.message}
        </p>
      )}

      {phase.name === "done" && (
        <div className="mic-test-results">
          <ul className="practice-advice">
            {micTestAdvice(phase.stats.phrase).map((advice) => (
              <li key={advice}>{advice}</li>
            ))}
          </ul>
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col"></th>
                <th scope="col">Nota sostenida</th>
                <th scope="col">Frase</th>
              </tr>
            </thead>
            <tbody>
              <StatRow
                label="Voz detectada"
                stats={phase.stats}
                format={(s) => percent(s.voicedShare)}
              />
              <StatRow
                label="Descartado por silencio"
                stats={phase.stats}
                format={(s) => percent(s.gatedShare)}
              />
              <StatRow
                label="Descartado por poco claro"
                stats={phase.stats}
                format={(s) => percent(s.rejectedShare)}
              />
              <StatRow
                label="Nivel (umbral de silencio: −46 dBFS)"
                stats={phase.stats}
                format={(s) =>
                  s.medianLevelDb === null ? "—" : `${String(s.medianLevelDb)} dBFS`
                }
              />
              <StatRow
                label="Claridad con voz / descartada (mínimo 0,85)"
                stats={phase.stats}
                format={(s) =>
                  `${String(s.voicedClarity ?? "—")} / ${String(s.rejectedClarity ?? "—")}`
                }
              />
              <StatRow
                label="Tramos de voz (mediana)"
                stats={phase.stats}
                format={(s) =>
                  s.medianVoicedRunMs === null
                    ? "—"
                    : `${String(s.medianVoicedRunMs)} ms`
                }
              />
            </tbody>
          </table>
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard
                .writeText(JSON.stringify(phase.stats, null, 2))
                .then(() => {
                  setCopied(true);
                });
            }}
          >
            {copied ? "Copiado" : "Copiar resultados"}
          </button>
        </div>
      )}
    </section>
  );
}

function StatRow({
  label,
  stats,
  format,
}: {
  label: string;
  stats: Record<StepId, MicTestStats>;
  format: (stats: MicTestStats) => string;
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{format(stats.sustained)}</td>
      <td>{format(stats.phrase)}</td>
    </tr>
  );
}
