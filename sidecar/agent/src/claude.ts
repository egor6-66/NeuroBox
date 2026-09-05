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

import { conversationOf, remember } from "./conversations.js";

export interface RunRequest {
  prompt: string;
  /** Инструкция из знание-семян рецепта. */
  systemPrompt?: string;
  /** Серверы рецепта в исходном формате MCP: `{ "имя": { ... } }`. */
  mcpServers?: Record<string, unknown>;
  /**
   * Контекст разговора A2A.
   *
   * Продолжать или начинать — решает адаптер, а не тот, кто ставит задачу: он один знает, была
   * ли уже заведена беседа. Разбор — в `conversations.ts`.
   */
  contextId?: string;
}

/**
 * Во что обошёлся прогон.
 *
 * Кэш-токены считаются отдельно, и это не педантизм: на коротком вопросе их бывает на порядок
 * больше обычных, и учёт без них показывал бы копейки там, где потрачено ощутимо.
 */
export interface Usage {
  inputTokens?: number;
  outputTokens?: number;
  cacheCreationTokens?: number;
  cacheReadTokens?: number;
  costUsd?: number;
  durationMs?: number;
}

export interface RunResult {
  ok: boolean;
  text: string;
  usage?: Usage;
  /** Идентификатор беседы, который CLI назначил себе сам. */
  conversationId?: string;
}

function usageOf(report: Record<string, unknown>): Usage {
  const raw = (report["usage"] ?? {}) as Record<string, unknown>;
  const number = (value: unknown): number | undefined =>
    typeof value === "number" && Number.isFinite(value) ? value : undefined;

  return {
    inputTokens: number(raw["input_tokens"]),
    outputTokens: number(raw["output_tokens"]),
    cacheCreationTokens: number(raw["cache_creation_input_tokens"]),
    cacheReadTokens: number(raw["cache_read_input_tokens"]),
    costUsd: number(report["total_cost_usd"]),
    durationMs: number(report["duration_ms"]),
  };
}

/**
 * Отдать CLI задачу и дождаться ответа.
 *
 * Ошибка возвращается значением, а не броском: неудача прогона — обычное дело, и вызывающий
 * обязан рассказать о ней человеку словами, а не поймать исключение.
 */
export async function run(request: RunRequest, signal?: AbortSignal): Promise<RunResult> {
  // Отчёт объектом, а не голым текстом: только так наружу доезжают расход и признак неудачи.
  // Разбирать текст на предмет «похоже на ошибку» было бы гаданием.
  const args = ["-p", request.prompt, "--output-format", "json"];

  // Беседа продолжается по идентификатору, который CLI назначил себе сам. Своего мы ему не
  // навязываем: назначенный нами однажды окажется занятым, и запуск упадёт на ровном месте.
  const conversation = request.contextId ? await conversationOf(request.contextId) : undefined;
  if (conversation) {
    args.push("--resume", conversation);
  }

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
    const result = await once(args, signal);
    if (request.contextId && result.conversationId) {
      await remember(request.contextId, result.conversationId);
    }
    return result;
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
      // Причина берётся из stderr, а если он пуст — хотя бы код возврата. Пустое сообщение
      // об ошибке хуже некрасивого: по нему нечего искать.
      const reason = err.trim() || out.trim() || `код возврата ${code}`;

      if (code !== 0) {
        resolve({ ok: false, text: reason });
        return;
      }

      let report: Record<string, unknown>;
      try {
        report = JSON.parse(out) as Record<string, unknown>;
      } catch {
        // Нулевой код и неразбираемый вывод — состояние, которого быть не должно. Молча отдать
        // сырой текст значило бы потерять и расход, и признак неудачи.
        resolve({ ok: false, text: `ответ не разобрался как отчёт: ${out.slice(0, 300)}` });
        return;
      }

      const text = typeof report["result"] === "string" ? report["result"].trim() : "";
      const usage = usageOf(report);
      const conversationId =
        typeof report["session_id"] === "string" ? report["session_id"] : undefined;

      // Признак неудачи берётся из отчёта, а не выводится из кода возврата: CLI завершается
      // успешно и тогда, когда сам прогон не удался.
      if (report["is_error"] === true) {
        resolve({ ok: false, text: text || reason, usage, conversationId });
        return;
      }

      resolve({ ok: true, text, usage, conversationId });
    });
  });
}
