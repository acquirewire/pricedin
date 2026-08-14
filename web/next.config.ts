import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Every route is prerendered — the data is a build-time JSON snapshot and
  // there is no server-side work to do — so the app exports to plain static
  // files. That means it can be hosted anywhere, including GitHub Pages, with
  // no runtime, no database and nothing to keep alive.
  output: "export",

  // Pages serves a project site from /<repo>, so the asset prefix has to match.
  // Set PAGES_BASE_PATH=/pricedin in CI; leave it unset everywhere else.
  basePath: process.env.PAGES_BASE_PATH || undefined,

  // Static hosts map /about -> /about/index.html rather than /about.html.
  trailingSlash: true,

  images: { unoptimized: true },
};

export default nextConfig;
