import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { getAudioContext } from "../audio/context";
import { Microphone, microphoneErrorMessage } from "../audio/microphone";
import { MicTest } from "../components/MicTest";
import { MIN_MATCHED, type CalibrationResult } from "../calibration/detect";
import { BEEP_COUNT, calibrate } from "../calibration/run";
import { useAnimationFrame } from "../hooks/useAnimationFrame";
import { loadLatency, saveLatency } from "../settings/latency";

type Phase =
  | { name: "intro" }
  | { name: "listening"; beepTimes: readonly number[] | null }
  | { name: "result"; result: CalibrationResult }
  | { name: "error"; message: string };

const FAILURE_HELP: Record<"no_signal" | "inconsistent", string> = {
  no_signal: `Se detectaron pocos golpes (hacen falta ${MIN_MATCHED} de ${BEEP_COUNT}). Acercate al micrófono y aplaudí más fuerte.`,
  inconsistent:
    "Los golpes no coincidieron entre sí. Intentá seguir el ritmo de cerca.",
};

export function CalibrationPage() {
  const [phase, setPhase] = useState<Phase>({ name: "intro" });
  const [saved, setSaved] = useState(loadLatency);
  const [manual, setManual] = useState(() => String(loadLatency() ?? 0));
  const microphone = useRef<Microphone | null>(null);

  useEffect(
    () => () => {
      microphone.current?.close();
    },
    [],
  );

  /** The microphone, opened once and shared with the microphone test. */
  const getMicrophone = async () => {
    const context = getAudioContext();
    await context.resume();
    microphone.current ??= await Microphone.open(context);
    return microphone.current;
  };

  const start = async () => {
    setPhase({ name: "listening", beepTimes: null });
    try {
      const mic = await getMicrophone();
      const result = await calibrate(getAudioContext(), mic, (beepTimes) => {
        setPhase({ name: "listening", beepTimes });
      });
      setPhase({ name: "result", result });
    } catch (error) {
      setPhase({ name: "error", message: microphoneErrorMessage(error) });
    }
  };

  const save = (latencyMs: number) => {
    if (saveLatency(latencyMs)) setSaved(Math.round(latencyMs));
  };

  return (
    <section className="calibration">
      <h1>Calibrar latencia</h1>
      <p>
        Los auriculares, el micrófono y la placa de sonido agregan un retraso. Lo
        medimos para no penalizarte por cantar a tiempo.
      </p>
      <ol>
        <li>Usá los auriculares o parlantes con los que vas a cantar.</li>
        <li>
          Vas a escuchar {BEEP_COUNT} pitidos a ritmo constante: aplaudí (o decí “ta”)
          justo con cada uno.
        </li>
      </ol>
      <p className="muted">
        Latencia guardada: {saved === null ? "sin calibrar" : `${saved} ms`}
      </p>

      {phase.name === "listening" ? (
        <Beat beepTimes={phase.beepTimes} />
      ) : (
        <button type="button" className="primary" onClick={() => void start()}>
          {phase.name === "intro" ? "Empezar" : "Repetir"}
        </button>
      )}

      {phase.name === "error" && (
        <p role="alert" className="error-box">
          {phase.message}
        </p>
      )}

      {phase.name === "result" &&
        (phase.result.ok ? (
          <div className="calibration-result" role="status">
            <p className="calibration-value">{phase.result.latencyMs} ms</p>
            <p className="muted">
              {phase.result.matched} de {BEEP_COUNT} golpes, ±{phase.result.spreadMs} ms
            </p>
            <button
              type="button"
              className="primary"
              disabled={saved === phase.result.latencyMs}
              onClick={() => {
                if (phase.result.ok) save(phase.result.latencyMs);
              }}
            >
              {saved === phase.result.latencyMs ? "En uso" : "Usar esta latencia"}
            </button>
          </div>
        ) : (
          <p role="alert" className="error-box">
            {FAILURE_HELP[phase.result.reason]}
          </p>
        ))}

      <details className="calibration-manual">
        <summary>Ajustar a mano</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const value = Number(manual);
            if (Number.isFinite(value)) save(value);
          }}
        >
          <label>
            Latencia (ms){" "}
            <input
              type="number"
              min={-500}
              max={1000}
              step={1}
              value={manual}
              onChange={(event) => {
                setManual(event.target.value);
              }}
            />
          </label>{" "}
          <button type="submit">Guardar</button>
        </form>
      </details>

      <MicTest getMicrophone={getMicrophone} />

      <p>
        <Link to="/">Volver al catálogo</Link>
      </p>
    </section>
  );
}

/** Shows which beep is playing, so the player can follow the beat. */
function Beat({ beepTimes }: { beepTimes: readonly number[] | null }) {
  const [count, setCount] = useState(0);

  useAnimationFrame(() => {
    if (beepTimes === null) return;
    const now = getAudioContext().currentTime;
    const played = beepTimes.filter((time) => time <= now).length;
    setCount((current) => (current === played ? current : played));
  }, beepTimes !== null);

  return (
    <div className="beat" role="status">
      <div className="beat-dots" aria-hidden="true">
        {Array.from({ length: BEEP_COUNT }, (_, i) => (
          <span key={i} className={i < count ? "beat-dot on" : "beat-dot"} />
        ))}
      </div>
      <p>{count === 0 ? "Preparate…" : `Pitido ${count} de ${BEEP_COUNT}`}</p>
    </div>
  );
}
