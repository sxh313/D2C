import path from "path";
import fs from "fs";
import dotenv from "dotenv";
import { defineConfig } from "vite";
import checker from "vite-plugin-checker";
import react from "@vitejs/plugin-react";
import { createHtmlPlugin } from "vite-plugin-html";

// https://vitejs.dev/config/
export default () => {
  const envPath = path.resolve(__dirname, "../../.env");
  const local = fs.existsSync(envPath) ? dotenv.parse(fs.readFileSync(envPath)) : {};
  const backendHost = local.D2C_BACKEND_HOST || "127.0.0.1";
  const backendPort = local.D2C_BACKEND_PORT || "7001";
  const CODEGEN_BACKEND = `http://${backendHost}:${backendPort}`;

  return defineConfig({
    base: "",
    envDir: false,
    server: {
      // Listen on all interfaces so sandbox preview tunnels can reach the
      // dev server (default binding is loopback-only).
      host: local.D2C_WEB_HOST || "127.0.0.1",
      port: Number(local.D2C_WEB_PORT || "5173"),
      strictPort: true,
      // Route backend traffic through the frontend origin so the app works
      // via tunnels/preview URLs (no hardcoded localhost from the browser).
      proxy: {
        "/generate-code": { target: CODEGEN_BACKEND, ws: true },
        "/api": { target: CODEGEN_BACKEND, ws: true },
        "/local-assets": { target: CODEGEN_BACKEND },
      },
    },
    plugins: [
      react(),
      checker({ 
        typescript: true
      }),
      createHtmlPlugin({
        inject: {
          data: {
            injectHead: process.env.VITE_IS_DEPLOYED
              ? '<script defer="" data-domain="screenshottocode.com" src="https://plausible.io/js/script.js"></script>'
              : "",
          },
        },
      }),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
  });
};
