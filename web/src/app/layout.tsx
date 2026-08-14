import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";
import { SiteHeader } from "@/components/site-header";
import { meta } from "@/lib/data";

// IBM Plex reads as engineered rather than promotional — the difference
// between looking like infrastructure and looking like a landing page.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Priced In — earnings expectations",
    template: "%s · Priced In",
  },
  description:
    "Upcoming US earnings, what the options market has already priced in, and " +
    "an honest account of which signals survive out-of-sample testing.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const generated = new Date(meta.generated).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <html
      lang="en-GB"
      suppressHydrationWarning
      className={`${plexSans.variable} ${plexMono.variable} h-full`}
    >
      <body className="flex min-h-full flex-col text-[14px]">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <SiteHeader generated={generated} />
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-5 pb-24 pt-7 sm:px-7">
            {children}
          </main>
          <footer className="border-t">
            <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-5 text-[11.5px] text-muted-foreground sm:px-7">
              <span>
                Research tool. Not investment advice, and not a solicitation to
                trade.
              </span>
              <span className="font-mono">
                {meta.universe.toLocaleString("en-GB")} names ·{" "}
                {meta.historical_prints.toLocaleString("en-GB")} historical
                prints
              </span>
            </div>
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
