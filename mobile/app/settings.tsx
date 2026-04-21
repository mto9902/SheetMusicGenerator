import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { ChipGroup } from "@/src/components/ChipGroup";
import { SurfaceCard } from "@/src/components/SurfaceCard";
import { TopBar } from "@/src/components/TopBar";
import { getSettings, updateSettings } from "@/src/db/database";
import { EXERCISE_OPTIONS } from "@/src/lib/options";
import { Colors } from "@/src/theme/colors";
import type { AppSettings } from "@/src/types/exercise";

const SCALE_OPTIONS = [
  { value: 0.9, label: "Small" },
  { value: 1, label: "Normal" },
  { value: 1.15, label: "Large" },
  { value: 1.3, label: "XL" },
];

export default function SettingsScreen() {
  const router = useRouter();
  const [settings, setSettingsState] = useState<AppSettings | null>(null);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      void getSettings().then((next) => {
        if (!cancelled) {
          setSettingsState(next);
        }
      });

      return () => {
        cancelled = true;
      };
    }, []),
  );

  async function handleSave() {
    if (!settings) {
      return;
    }

    await updateSettings(settings);
    Alert.alert("Saved", "Your defaults are ready for the next piano session.");
    router.back();
  }

  if (!settings) {
    return null;
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <TopBar
        eyebrow="Settings"
        title="Practice defaults"
        subtitle="Keep your notation, phrase-reading focus, and warm-up defaults aligned with how you actually practice."
        onBack={() => router.back()}
      />

      <SurfaceCard>
        <ChipGroup
          label="Notation scale"
          value={settings.notationScale}
          options={SCALE_OPTIONS}
          onChange={(value) =>
            setSettingsState(
              (current) => current && { ...current, notationScale: Number(value) },
            )
          }
        />

        <ChipGroup
          label="Default hand position"
          value={settings.preferredHandPosition}
          options={EXERCISE_OPTIONS.handPositions}
          onChange={(value) =>
            setSettingsState(
              (current) =>
                current && {
                  ...current,
                  preferredHandPosition: value as AppSettings["preferredHandPosition"],
                },
            )
          }
        />

        <ChipGroup
          label="Default grade"
          value={settings.defaultGrade}
          options={EXERCISE_OPTIONS.grades.map((grade) => ({
            value: grade.value,
            label: grade.label,
          }))}
          onChange={(value) =>
            setSettingsState(
              (current) => current && { ...current, defaultGrade: Number(value) },
            )
          }
        />

        <ChipGroup
          label="Default reading focus"
          value={settings.defaultReadingFocus}
          options={EXERCISE_OPTIONS.readingFocuses}
          onChange={(value) =>
            setSettingsState(
              (current) =>
                current && {
                  ...current,
                  defaultReadingFocus: value as AppSettings["defaultReadingFocus"],
                },
            )
          }
        />

        <View style={styles.toggleRow}>
          <View style={styles.toggleCopy}>
            <Text style={styles.toggleTitle}>Enable metronome by default</Text>
            <Text style={styles.toggleBody}>
              Show the beat pulse automatically when you start practicing.
            </Text>
          </View>
          <Switch
            value={settings.metronomeDefault}
            onValueChange={(value) =>
              setSettingsState(
                (current) => current && { ...current, metronomeDefault: value },
              )
            }
          />
        </View>

        <View style={styles.toggleRow}>
          <View style={styles.toggleCopy}>
            <Text style={styles.toggleTitle}>Enable count-in by default</Text>
            <Text style={styles.toggleBody}>
              Give yourself a short visual count-in before each practice run.
            </Text>
          </View>
          <Switch
            value={settings.countInDefault}
            onValueChange={(value) =>
              setSettingsState(
                (current) => current && { ...current, countInDefault: value },
              )
            }
          />
        </View>
      </SurfaceCard>

      <TouchableOpacity style={styles.primaryButton} onPress={handleSave} activeOpacity={0.82}>
        <Text style={styles.primaryButtonText}>Save settings</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.bg,
  },
  content: {
    padding: 20,
    gap: 16,
    paddingBottom: 36,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.faint,
    paddingTop: 12,
  },
  toggleCopy: {
    flex: 1,
    gap: 4,
  },
  toggleTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: Colors.ink,
  },
  toggleBody: {
    fontSize: 13,
    lineHeight: 20,
    color: Colors.muted,
  },
  primaryButton: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: Colors.accent,
    borderWidth: 1,
    borderColor: Colors.accent,
    paddingVertical: 16,
  },
  primaryButtonText: {
    color: "#fff",
    fontSize: 15,
    fontWeight: "800",
  },
});
