import { defineConfig } from "vite";

// Output is shipped as package data. Everything is bundled locally: no CDN, no runtime fetches
// except the viewer's own /api on 127.0.0.1.
export default defineConfig(({ mode }) => ({
  base: "./",
  build: {
    outDir: "../prism/viewer_dist",
    emptyOutDir: mode !== "dashboard",
    assetsInlineLimit: 100000,
    cssCodeSplit: false,
    sourcemap: false,
    rollupOptions: {
      input: mode === "dashboard" ? "dashboard.html" : "index.html",
      output: {
        entryFileNames: mode === "dashboard" ? "assets/dashboard.js" : "assets/viewer.js",
        assetFileNames: mode === "dashboard" ? "assets/dashboard[extname]" : "assets/viewer[extname]",
        inlineDynamicImports: true,
      },
    },
  },
}));
