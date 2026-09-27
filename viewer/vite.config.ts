import { defineConfig } from "vite";

// Output is shipped as package data. Everything is bundled locally: no CDN, no runtime fetches
// except the viewer's own /api on 127.0.0.1.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../prism/viewer_dist",
    emptyOutDir: true,
    assetsInlineLimit: 100000,
    cssCodeSplit: false,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/viewer.js",
        assetFileNames: "assets/viewer[extname]",
        inlineDynamicImports: true,
      },
    },
  },
});
