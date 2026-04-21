export function formatTimeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.max(1, Math.floor(diffMs / 60000));

  if (mins < 60) return `${mins}m ago`;

  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatDuration(seconds: number) {
  const mins = Math.floor(seconds / 60);
  const remainder = seconds % 60;

  if (mins === 0) {
    return `${remainder}s`;
  }

  return `${mins}m ${String(remainder).padStart(2, "0")}s`;
}

export function formatModeLabel(mode: "piano" | "rhythm") {
  return mode === "piano" ? "Piano reading" : "Piano rhythm";
}

export function formatHandPositionLabel(position: "C" | "G" | "D" | "F" | "Bb") {
  return `${position} position`;
}

export function formatHandActivityLabel(
  activity: "right-only" | "left-only" | "both",
) {
  if (activity === "right-only") {
    return "Right hand";
  }

  if (activity === "left-only") {
    return "Left hand";
  }

  return "Both hands";
}
