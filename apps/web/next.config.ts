import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Fully client-side app — a static export keeps deployment boring
  // (any static file server or CDN can host it; no Node runtime needed).
  output: "export",
};

export default config;
