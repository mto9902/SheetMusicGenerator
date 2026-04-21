import { Ionicons } from "@expo/vector-icons";
import { ReactNode } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { Colors } from "@/src/theme/colors";

type Props = {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  rightSlot?: ReactNode;
  onBack?: () => void;
};

export function TopBar({ eyebrow, title, subtitle, rightSlot, onBack }: Props) {
  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <View style={styles.copy}>
          <View style={styles.titleRow}>
            {onBack ? (
              <TouchableOpacity onPress={onBack} style={styles.backButton} activeOpacity={0.8}>
                <Ionicons name="arrow-back" size={20} color={Colors.ink} />
              </TouchableOpacity>
            ) : null}
            <View style={styles.titleCopy}>
              {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
              <Text style={styles.title}>{title}</Text>
            </View>
          </View>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        {rightSlot ? <View style={styles.rightSlot}>{rightSlot}</View> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 10,
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
  },
  copy: {
    flex: 1,
    gap: 8,
  },
  rightSlot: {
    paddingTop: 4,
  },
  titleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  backButton: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
  },
  titleCopy: {
    flex: 1,
    gap: 4,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 1.1,
    color: Colors.muted,
  },
  title: {
    fontSize: 30,
    lineHeight: 36,
    fontWeight: "800",
    color: Colors.ink,
  },
  subtitle: {
    fontSize: 15,
    lineHeight: 22,
    color: Colors.muted,
  },
});
