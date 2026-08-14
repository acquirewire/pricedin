"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Calendar" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/methodology", label: "Methodology" },
];

export function SiteHeader({ generated }: { generated?: string }) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur-sm">
      <div className="mx-auto flex h-13 max-w-[1400px] items-center gap-7 px-5 py-3 sm:px-7">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-[-0.02em]">
            Priced In
          </span>
          <span className="hidden text-[11px] text-muted-foreground sm:inline">
            earnings expectations
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-sm px-2.5 py-1 text-[13px] transition-colors",
                  active
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {item.label}
                {active && (
                  <span className="mt-1 block h-px bg-foreground" aria-hidden />
                )}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {generated && (
            <span className="hidden font-mono text-[11px] text-muted-foreground md:inline">
              {generated}
            </span>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
