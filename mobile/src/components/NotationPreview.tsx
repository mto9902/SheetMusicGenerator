import { useMemo } from "react";
import { StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { SvgXml } from "react-native-svg";

import { Colors } from "@/src/theme/colors";

type Props = {
  svg: string;
  scale?: number;
};

function parseSvgDimensions(svg: string): { width: number; height: number } | null {
  const match = svg.match(/width="([\d.]+)px"\s+height="([\d.]+)px"/);
  if (match) {
    return { width: parseFloat(match[1]), height: parseFloat(match[2]) };
  }
  const vbMatch = svg.match(/viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"/);
  if (vbMatch) {
    return { width: parseFloat(vbMatch[1]), height: parseFloat(vbMatch[2]) };
  }
  return null;
}

export function NotationPreview({ svg, scale = 1 }: Props) {
  const { width: screenWidth } = useWindowDimensions();

  const displayHeight = useMemo(() => {
    const dims = svg ? parseSvgDimensions(svg) : null;
    if (!dims) return Math.round(520 * scale);

    // Scale the SVG proportionally to fill available width (minus padding)
    const availableWidth = (screenWidth - 60) * scale;
    const ratio = availableWidth / dims.width;
    return Math.round(dims.height * ratio);
  }, [svg, scale, screenWidth]);

  if (!svg) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>Notation preview unavailable.</Text>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <SvgXml xml={svg} width="100%" height={displayHeight} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    width: "100%",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: "#fff",
    padding: 10,
  },
  empty: {
    minHeight: 240,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: Colors.faint,
    backgroundColor: Colors.paper,
  },
  emptyText: {
    color: Colors.muted,
  },
});
