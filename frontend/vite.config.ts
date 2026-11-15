import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import AutoImport from "unplugin-auto-import/vite";
import UnoCSS from "unocss/vite";
import { resolve } from "node:path";
export default defineConfig({
  plugins: [vue(), UnoCSS(), AutoImport({ imports: ["vue", "vue-router"], dts: false })],
  resolve: { alias: { "@": resolve(import.meta.dirname, "src") } },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api/v1/auth": process.env.AUTH_PROXY_URL || "http://127.0.0.1:8081",
      "/api/v1/users": process.env.AUTH_PROXY_URL || "http://127.0.0.1:8081",
      "/api/v1/files": process.env.FILE_PROXY_URL || "http://127.0.0.1:8082",
      "/api/v1/directories": process.env.FILE_PROXY_URL || "http://127.0.0.1:8082",
      "/api/v1/quota": process.env.FILE_PROXY_URL || "http://127.0.0.1:8082",
      "/api/v1/shares": process.env.SHARE_PROXY_URL || "http://127.0.0.1:8083",
      "/api/v1/s/": process.env.SHARE_PROXY_URL || "http://127.0.0.1:8083",
    },
  },
});
