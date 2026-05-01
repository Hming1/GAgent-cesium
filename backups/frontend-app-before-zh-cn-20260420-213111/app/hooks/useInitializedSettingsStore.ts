import { useEffect, useRef } from "react";
import { useSettingsStore, SettingsState } from "../stores/settingsStore";

// Global flag to ensure initialization happens only once across ALL hook instances
// This prevents race conditions when multiple components use the hook simultaneously
//全局标志，确保在所有钩子实例中初始化只发生一次//这可以防止多个组件同时使用钩子时出现竞争条件
let globalInitStarted = false;

export function useInitializedSettingsStore<T>(
  selector: (state: SettingsState) => T,
): T {
  const value = useSettingsStore(selector);
  const initializeIfNeeded = useSettingsStore((s) => s.initializeIfNeeded);
  const initialized = useSettingsStore((s) => s.initialized);

  useEffect(() => {
    // Use global flag to ensure only ONE initialization attempt across all hook instances
    if (!initialized && !globalInitStarted) {
      globalInitStarted = true;
      initializeIfNeeded();
    }
  }, [initialized, initializeIfNeeded]);

  return value;
}
