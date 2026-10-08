import type { ReactNode } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PracticeWord } from "../api/types";
import { SERIES_COLORS } from "../lib/chartColors";
import { midiNoteName } from "../lib/pitch";
import { pitchDomain, pitchTicks, type ChartRow } from "../lib/practice";

const GRID = "#2a2f3c";
const MUTED = "#9097a8";

interface PitchChartProps {
  rows: readonly ChartRow[];
  words: readonly PracticeWord[];
  /** Extra layers (admin diagnostics), drawn under the curves. */
  children?: ReactNode;
  height?: number;
}

function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1).replace(".", ",")} s`;
}

/** The part of Recharts' tooltip props this chart uses. */
interface PitchTooltipProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
  label?: string | number;
}

function PitchTooltip({ active, payload = [], label }: PitchTooltipProps) {
  if (!active || payload.length === 0) return null;
  const row = payload[0]?.payload as ChartRow | undefined;
  if (row === undefined) return null;
  const difference =
    row.reference !== null && row.voice !== null ? row.voice - row.reference : null;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-title">{formatSeconds(Number(label))}</p>
      <p>
        <span
          className="chart-swatch"
          style={{ background: SERIES_COLORS.reference }}
        />
        Melodía: {row.reference === null ? "—" : midiNoteName(row.reference)}
      </p>
      <p>
        <span className="chart-swatch" style={{ background: SERIES_COLORS.voice }} />
        Tu voz: {row.voice === null ? "—" : midiNoteName(row.voice)}
        {difference !== null &&
          ` (${difference >= 0 ? "+" : "−"}${Math.abs(difference).toFixed(1).replace(".", ",")} st)`}
      </p>
    </div>
  );
}

/** Reference melody vs the player's voice over one line, notes on the y axis. */
export function PitchChart({ rows, words, children, height = 260 }: PitchChartProps) {
  const domain = pitchDomain(rows);
  const durationS = rows.at(-1)?.timeS ?? 0;
  return (
    <figure className="pitch-chart" aria-label="Melodía y tu voz a lo largo del verso">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 24, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="timeS"
            type="number"
            domain={[0, durationS]}
            tickFormatter={formatSeconds}
            stroke={MUTED}
            tick={{ fill: MUTED, fontSize: 12 }}
            tickLine={false}
          />
          <YAxis
            domain={domain}
            ticks={pitchTicks(domain)}
            tickFormatter={midiNoteName}
            stroke={MUTED}
            tick={{ fill: MUTED, fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={44}
          />
          {children}
          {words.map((word) => (
            <ReferenceLine
              key={`${word.text}-${String(word.start_ms)}`}
              x={word.start_ms / 1000}
              stroke={GRID}
              label={{
                value: word.text,
                position: "insideTopLeft",
                fill: MUTED,
                fontSize: 11,
              }}
            />
          ))}
          <Tooltip
            content={(props: PitchTooltipProps) => <PitchTooltip {...props} />}
            cursor={{ stroke: MUTED, strokeDasharray: "3 3" }}
            isAnimationActive={false}
          />
          <Line
            dataKey="reference"
            name="Melodía"
            stroke={SERIES_COLORS.reference}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
          <Line
            dataKey="voice"
            name="Tu voz"
            stroke={SERIES_COLORS.voice}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
          <Legend
            height={28}
            iconType="plainline"
            // Text stays in text ink; the line swatch carries the identity.
            formatter={(value: string) => (
              <span className="chart-legend-label">{value}</span>
            )}
          />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}
