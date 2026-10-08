import type { LineScoreMessage } from "../api/types";

function verdict(score: LineScoreMessage): string {
  if (!score.scorable) return "Verso sin melodía: no puntúa";
  if ((score.score ?? 0) >= 85) return "¡Excelente!";
  if (score.hit) return "¡Bien!";
  if ((score.score ?? 0) >= 30) return "Casi…";
  return "Fuera de tono";
}

/**
 * Feedback for the last scored line. Render it with `key={line_index}` so it
 * re-mounts per line and replays its entrance animation.
 */
export function ScoreCard({ score }: { score: LineScoreMessage }) {
  const tone = !score.scorable ? "neutral" : score.hit ? "hit" : "miss";
  return (
    <div className={`score-card ${tone}`} role="status" aria-label="Puntaje del verso">
      <span className="score-card-value">
        {score.scorable && score.score !== null ? Math.round(score.score) : "–"}
      </span>
      <span className="score-card-verdict">{verdict(score)}</span>
      {score.streak > 1 && (
        <span className="score-card-streak">Racha ×{score.streak}</span>
      )}
    </div>
  );
}
