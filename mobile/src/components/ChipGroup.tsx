import { StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { Colors } from "@/src/theme/colors";

type Option<T extends string | number> = {
  value: T;
  label: string;
};

type Props<T extends string | number> = {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
};

export function ChipGroup<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: Props<T>) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.row}>
        {options.map((option) => {
          const active = option.value === value;
          return (
            <TouchableOpacity
              key={String(option.value)}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => onChange(option.value)}
              activeOpacity={0.82}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {option.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 10,
  },
  label: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1,
    color: Colors.muted,
  },
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
  },
  chipActive: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
  chipText: {
    fontSize: 13,
    fontWeight: "600",
    color: Colors.ink,
  },
  chipTextActive: {
    color: "#fff",
  },
});
