import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import "react-native-reanimated";

import { initializeDatabase } from "@/src/db/database";
import { Colors } from "@/src/theme/colors";

export {
  ErrorBoundary,
} from "expo-router";

export const unstable_settings = {
  initialRouteName: "(tabs)",
};

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const queryClient = useMemo(() => new QueryClient(), []);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const init = async () => {
      try {
        await initializeDatabase();
      } catch (error) {
        console.warn("DB init failed, retrying once:", error);
        try {
          await initializeDatabase();
        } catch (retryError) {
          console.error("DB init failed after retry:", retryError);
        }
      }
      if (!cancelled) {
        setReady(true);
        await SplashScreen.hideAsync();
      }
    };

    void init();

    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <View
        style={{
          flex: 1,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: Colors.bg,
        }}
      >
        <ActivityIndicator color={Colors.accent} />
      </View>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="exercise/[id]" />
        <Stack.Screen name="settings" options={{ presentation: "modal" }} />
      </Stack>
    </QueryClientProvider>
  );
}
