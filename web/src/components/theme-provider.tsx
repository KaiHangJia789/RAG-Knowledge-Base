"use client";

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";

type Theme = "dark" | "light";
const KEY = "rag-theme-v1";
const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void }>({ theme: "dark", setTheme: () => {} });

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("rag-theme-change", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("rag-theme-change", callback);
  };
}

function snapshot(): Theme {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useSyncExternalStore(subscribe, snapshot, () => "dark" as Theme);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const setTheme = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(KEY, next); } catch {}
    window.dispatchEvent(new Event("rag-theme-change"));
  }, []);
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
