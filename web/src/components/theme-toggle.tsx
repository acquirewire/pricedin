"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Render the frame before mount so the header does not reflow when the
  // theme resolves.
  const isDark = mounted && resolvedTheme === "dark";

  return (
    <button
      type="button"
      aria-label="Toggle colour scheme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      {mounted ? (
        isDark ? (
          <Sun className="size-3.5" />
        ) : (
          <Moon className="size-3.5" />
        )
      ) : (
        <span className="size-3.5" />
      )}
    </button>
  );
}
