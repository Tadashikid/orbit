import { useCallback, useSyncExternalStore } from "react";

function useMedia(query: string) {
  return useSyncExternalStore(
    useCallback(
      (notify: () => void) => {
        const media = window.matchMedia(query);
        media.addEventListener("change", notify);
        return () => media.removeEventListener("change", notify);
      },
      [query],
    ),
    useCallback(
      () => typeof window !== "undefined" && window.matchMedia(query).matches,
      [query],
    ),
    () => false,
  );
}
export function useMotionPreferences() {
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const pointer = useMedia("(hover: hover) and (pointer: fine)");
  return { reduced, pointer };
}
export const revealEase = [0.22, 1, 0.36, 1] as const;
