import { PropsWithChildren } from "react";
import { StyleSheet, View, ViewProps } from "react-native";

import { Colors } from "@/src/theme/colors";

type Props = PropsWithChildren<ViewProps>;

export function SurfaceCard({ children, style, ...rest }: Props) {
  return (
    <View style={[styles.card, style]} {...rest}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.paper,
    borderWidth: 1,
    borderColor: Colors.faint,
    padding: 18,
    gap: 12,
  },
});
