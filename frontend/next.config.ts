import type { NextConfig } from "next";
import { resolve } from "node:path";

const nextConfig: NextConfig = {
  /* config options here */
  output: "standalone",
  
  // Allow Playwright to make cross-origin requests during testing  
  allowedDevOrigins: [
    'http://127.0.0.1:3000',
    'http://localhost:3000',
    'http://0.0.0.0:3000',
  ],
  
  // Disable ESLint during production builds (errors will still be caught in development)
  eslint: {
    ignoreDuringBuilds: true,
  },
  
  // Disable TypeScript type checking during production builds (use separate CI check)
  typescript: {
    ignoreBuildErrors: true,
  },
  
  // Increase body size limit for server actions to match nginx (100MB)
  experimental: {
    serverActions: {
      bodySizeLimit: '1000mb'
    }
  },
  
  // Rewrite /map to root page (nginx serves loading page at /, redirects to /map when ready)
  async rewrites() {
    return [
      {
        source: '/map',
        destination: '/',
      },
    ];
  },

  // Cesium's optional SPZ Gaussian-splat decoder bundles raw WebAssembly in a
  // template literal. Next/Webpack emits that binary as a JavaScript chunk,
  // which Chromium cannot parse. Normal Cesium maps do not use SPZ assets, so
  // replace only this experimental decoder with an explicit unsupported error.
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@spz-loader/core": resolve(__dirname, "app/shims/spz-loader.ts"),
    };
    return config;
  },
};

export default nextConfig;
