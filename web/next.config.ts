import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Tailwind v4 runs as a Turbopack loader (added by create-next-app).
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Keep the dev-mode badge out of the video recording.
  devIndicators: false,
};

export default nextConfig;
