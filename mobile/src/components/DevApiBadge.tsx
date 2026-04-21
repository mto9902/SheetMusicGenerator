import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { API_BASE } from "@/src/lib/api";
import { Colors } from "@/src/theme/colors";

type Props = {
  note?: string;
};

function apiLabel() {
  try {
    const parsed = new URL(API_BASE);
    return parsed.origin;
  } catch {
    return API_BASE;
  }
}

export function DevApiBadge({ note }: Props) {
  const [build, setBuild] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadBuild() {
      try {
        const response = await fetch(`${API_BASE}/v1/health`);
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as { build?: string };
        if (!cancelled && payload.build) {
          setBuild(payload.build);
        }
      } catch {
        // Best-effort dev signal only.
      }
    }

    if (__DEV__) {
      void loadBuild();
    }

    return () => {
      cancelled = true;
    };
  }, []);

  if (!__DEV__) {
    return null;
  }

  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>Dev API</Text>
      <Text style={styles.value}>{apiLabel()}</Text>
      {build ? <Text style={styles.build}>Build {build}</Text> : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: "#fff",
    paddingHorizontal: 10,
    paddingVertical: 8,
    gap: 2,
  },
  label: {
    color: Colors.muted,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    fontWeight: "700",
  },
  value: {
    color: Colors.ink,
    fontSize: 13,
    fontWeight: "700",
  },
  build: {
    color: Colors.muted,
    fontSize: 10,
  },
  note: {
    color: Colors.muted,
    fontSize: 11,
  },
});
