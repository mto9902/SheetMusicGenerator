import { useMemo } from "react";
import { Text, useWindowDimensions, View } from "react-native";

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

function makeResponsiveSvg(svg: string, displayHeight: number): string {
  return svg.replace(
    /<svg\b([^>]*)>/,
    (_match, attrs: string) =>
      `<svg${attrs} width="100%" height="${displayHeight}px" style="display:block;width:100%;height:${displayHeight}px;overflow:visible">`,
  );
}

export function NotationPreview({ svg, scale = 1 }: Props) {
  const { width: screenWidth } = useWindowDimensions();

  const displayHeight = useMemo(() => {
    const dims = svg ? parseSvgDimensions(svg) : null;
    if (!dims) return Math.round(520 * scale);

    const availableWidth = (screenWidth - 60) * scale;
    const ratio = availableWidth / dims.width;
    return Math.round(dims.height * ratio);
  }, [svg, scale, screenWidth]);

  const responsiveSvg = useMemo(() => {
    if (!svg) return "";
    return makeResponsiveSvg(svg, displayHeight);
  }, [displayHeight, svg]);

  if (!svg) {
    return (
      <View
        style={{
          minHeight: 240,
          alignItems: "center",
          justifyContent: "center",
          borderWidth: 1,
          borderColor: Colors.faint,
          backgroundColor: Colors.paper,
        }}
      >
        <Text style={{ color: Colors.muted }}>Notation preview unavailable.</Text>
      </View>
    );
  }

  return (
    <View
      style={{
        width: "100%",
        borderWidth: 1,
        borderColor: Colors.faint,
        backgroundColor: "#fff",
        padding: 10,
      }}
    >
      <div
        style={{ width: "100%", lineHeight: 0 }}
        dangerouslySetInnerHTML={{ __html: responsiveSvg }}
      />
    </View>
  );
}
