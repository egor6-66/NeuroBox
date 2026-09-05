import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import solid from "vite-plugin-solid";

export default defineConfig({
  plugins: [solid()],
  resolve: {
    alias: { "#": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // В разработке сервис живёт на соседнем порту. Проксируем, а не разрешаем чужие
    // источники: одинаковый источник в разработке и в сборке означает, что поведение
    // не расходится между ними.
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
