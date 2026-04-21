import type { ExerciseConfig, GeneratedExercise } from "@shared/types";

const defaultBase = "http://127.0.0.1:8000";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || defaultBase;

export async function generateExercise(config: ExerciseConfig & { seed: string }) {
  const response = await fetch(`${API_BASE}/v1/exercises/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Generation failed (${response.status})`);
  }

  return (await response.json()) as GeneratedExercise;
}

export async function fetchHealth() {
  const response = await fetch(`${API_BASE}/v1/health`);
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status})`);
  }
  return (await response.json()) as { ok: boolean; build?: string };
}
