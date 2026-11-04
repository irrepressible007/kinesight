import type { NextConfig } from "next";

// STATIC_EXPORT=1 emits plain files that the FastAPI backend serves in the single-container
// deployment. Export mode can't prerender partially, so those features are off there.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig: NextConfig = {
  output: staticExport ? "export" : undefined,
  cacheComponents: !staticExport,
  devIndicators: false,
  partialPrefetching: !staticExport,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
