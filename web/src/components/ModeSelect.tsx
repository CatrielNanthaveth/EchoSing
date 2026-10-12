import { MODES, type ScoringMode } from "../settings/mode";

/** Melody / rap selector; rap needs the vocals' level in the song's analysis. */
export function ModeSelect({
  value,
  rapAvailable,
  onChange,
}: {
  value: ScoringMode;
  rapAvailable: boolean;
  onChange: (mode: ScoringMode) => void;
}) {
  return (
    <label>
      Modo{" "}
      <select
        value={value}
        onChange={(event) => {
          onChange(event.target.value as ScoringMode);
        }}
      >
        {MODES.map((mode) => (
          <option
            key={mode.value}
            value={mode.value}
            disabled={mode.value === "rhythm" && !rapAvailable}
          >
            {mode.label} (
            {mode.value === "rhythm" && !rapAvailable
              ? "no disponible para esta canción"
              : mode.hint}
            )
          </option>
        ))}
      </select>
    </label>
  );
}
