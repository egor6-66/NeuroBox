/**
 * Запуск локального Claude Code. Всё, что знает про CLI, живёт здесь — снаружи только протокол.
 *
 * Развёртка отдаёт ровно то, что CLI принимает: инструкцию и список серверов. Поэтому
 * переходника между нашей моделью и его флагами почти нет — это и было доводом взять его
 * рантаймом.
 */

import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface RunRequest {
  prompt: string;
  /** Инструкция из знание-семян рецепта. */
  systemPrompt?: string;
  /** Серверы рецепта в исходном формате MCP: `{ "имя": { ... } }`. */
  mcpServers?: Record<string, unknown>;
}

export interface RunResult {
  ok: boolean;
  text: string;
}

/**
 * Отдать CLI задачу и дождаться ответа.
 *
 * Ошибка возвращается значением, а не броском: неудача прогона — обычное дело, и вызывающий
 * обязан рассказать о ней человеку словами, а не поймать исключение.
 */
export async function run(request: RunRequest, signal?: AbortSignal): Promise<RunResult> {
  const args = ["-p", request.prompt];

  if (request.systemPrompt) {
    args.push("--system-prompt", request.systemPrompt);
  }

  // Конфиг серверов передаётся файлом, а не строкой в аргументах: список тулзов бывает
  // длинным, а у командной строки есть предел, за которым запуск падает без внятной причины.
  let workDir: string | undefined;
  if (request.mcpServers && Object.keys(request.mcpServers).length > 0) {
    workDir = await mkdtemp(join(tmpdir(), "neurobox-mcp-"));
    const configPath = join(workDir, "mcp.json");
    await writeFile(configPath, JSON.stringify({ mcpServers: request.mcpServers }), "utf8");
    // --strict-mcp-config: агент видит ТОЛЬКО серверы рецепта. Без этого он подхватил бы
    // серверы из окружения, и рецепт перестал бы быть границей.
    args.push("--mcp-config", configPath, "--strict-mcp-config");
  }

  try {
    return await once(args, signal);
  } finally {
    if (workDir) {
      await rm(workDir, { recursive: true, force: true });
    }
  }
}

function once(args: string[], signal?: AbortSignal): Promise<RunResult> {
  return new Promise((resolve) => {
    // Вход закрыт намеренно: с открытым stdin CLI ждёт данных, которых никто не пришлёт, и
    // тратит на это несколько секунд впустую перед тем, как отказаться работать.
    const child = spawn("claude", args, { signal, stdio: ["ignore", "pipe", "pipe"] });

    let out = "";
    let err = "";
    child.stdout.on("data", (chunk) => (out += String(chunk)));
    child.stderr.on("data", (chunk) => (err += String(chunk)));

    child.on("error", (error) => {
      resolve({ ok: false, text: `не удалось запустить claude: ${error.message}` });
    });

    child.on("close", (code) => {
      if (code === 0) {
        resolve({ ok: true, text: out.trim() });
        return;
      }
      // Причина берётся из stderr, а если он пуст — хотя бы код возврата. Пустое сообщение
      // об ошибке хуже некрасивого: по нему нечего искать.
      const reason = err.trim() || out.trim() || `код возврата ${code}`;
      resolve({ ok: false, text: reason });
    });
  });
}
