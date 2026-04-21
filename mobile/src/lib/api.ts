import { Platform } from "react-native";

import type { ExerciseConfig, GeneratedExercise } from "@/src/types/exercise";

const nativeDefaultBase =
  Platform.OS === "android" ? "http://10.0.2.2:8000" : "http://127.0.0.1:8000";

export const API_BASE = process.env.EXPO_PUBLIC_API_BASE || nativeDefaultBase;

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
