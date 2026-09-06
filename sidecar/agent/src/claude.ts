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
import { type Done, lines, type Step, stepsOf } from "./stream.js";

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
export type OnStep = (step: Step) => void;

export async function run(
  request: RunRequest,
  signal?: AbortSignal,
  onStep?: OnStep,
): Promise<RunResult> {
  // Отчёт объектом, а не голым текстом: только так наружу доезжают расход и признак неудачи.
  // Разбирать текст на предмет «похоже на ошибку» было бы гаданием.
  // Потоком, а не одним отчётом: только так видно, что агент делает прямо сейчас, а не
  // спустя две минуты. Итоговый отчёт приходит последним событием и несёт расход.
  const args = ["-p", request.prompt, "--output-format", "stream-json", "--verbose"];

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

    // Разрешения выдаются ровно по серверам рецепта. Без этого агент в безголовом режиме
    // видит инструменты, но вызвать не может: спросить разрешения не у кого, и он честно
    // отказывается — со стороны это выглядит как сломанный агент.
    //
    // Именно по серверам, а не «разрешить всё»: рецепт — граница, и разрешения обязаны
    // совпадать с ней. Встроенные инструменты (файлы, оболочка) НЕ разрешаются: если они
    // понадобятся, это отдельное осознанное решение, а не побочный эффект.
    for (const name of Object.keys(request.mcpServers)) {
      args.push("--allowedTools", `mcp__${name}__*`);
    }
  }

  try {
    const result = await once(args, signal, onStep);
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

function once(args: string[], signal?: AbortSignal, onStep?: OnStep): Promise<RunResult> {
  return new Promise((resolve) => {
    // Вход закрыт намеренно: с открытым stdin CLI ждёт данных, которых никто не пришлёт, и
    // тратит на это несколько секунд впустую перед тем, как отказаться работать.
    const child = spawn("claude", args, { signal, stdio: ["ignore", "pipe", "pipe"] });

    const split = lines();
    let err = "";
    let last: Done | undefined;
    let raw = "";

    child.stdout.on("data", (chunk) => {
      raw += String(chunk);
      for (const event of split(String(chunk))) {
        for (const step of stepsOf(event)) {
          if (step.kind === "done") last = step;
          onStep?.(step);
        }
      }
    });
    child.stderr.on("data", (chunk) => (err += String(chunk)));

    child.on("error", (error) => {
      resolve({ ok: false, text: `не удалось запустить claude: ${error.message}` });
    });

    child.on("close", (code) => {
      // Причина берётся из stderr, а если он пуст — хотя бы код возврата. Пустое сообщение
      // об ошибке хуже некрасивого: по нему нечего искать.
      const reason = err.trim() || raw.trim() || `код возврата ${code}`;

      if (code !== 0) {
        resolve({ ok: false, text: reason });
        return;
      }

      if (!last) {
        // Нулевой код и ни одного итогового события — состояние, которого быть не должно.
        // Молча отдать сырой вывод значило бы потерять и расход, и признак неудачи.
        resolve({ ok: false, text: `поток кончился без итога: ${raw.slice(-300)}` });
        return;
      }

      // Признак неудачи берётся из итога, а не выводится из кода возврата: CLI завершается
      // успешно и тогда, когда сам прогон не удался.
      resolve({
        ok: last.ok,
        text: last.text || (last.ok ? "" : reason),
        usage: usageOf(last.report),
        conversationId: last.conversationId,
      });
    });
  });
}
