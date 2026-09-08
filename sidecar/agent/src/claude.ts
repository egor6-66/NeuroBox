/**
 * Запуск локального Claude Code. Всё, что знает про CLI, живёт здесь и в `session.ts` —
 * снаружи только протокол.
 *
 * Развёртка отдаёт ровно то, что CLI принимает: инструкцию и список серверов. Поэтому
 * переходника между нашей моделью и его флагами почти нет — это и было доводом взять его
 * рантаймом.
 *
 * Процесс CLI живёт сессию, а не сообщение: вместе с процессом жили бы и умирали соединения
 * с MCP, а серверы вправе держать состояние между вызовами. Жизнью процессов ведает
 * `session.ts`, здесь — соответствие «контекст → процесс».
 */

import { conversationOf, remember } from "./conversations.js";
import { CliSession, fingerprintOf, type OnStep } from "./session.js";

export type { OnStep } from "./session.js";

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

// Живые процессы по контекстам. Один контекст — один процесс: в нём и живёт состояние
// MCP-серверов между сообщениями, ради которого процессы стали долгоживущими.
const sessions = new Map<string, CliSession>();

async function sessionFor(
  contextId: string,
  spec: { systemPrompt?: string; mcpServers?: Record<string, unknown> },
): Promise<CliSession> {
  const wanted = fingerprintOf(spec);
  const live = sessions.get(contextId);
  if (live?.alive && live.fingerprint === wanted) return live;

  // Развёртка уходит в аргументы запуска, и сменить её у живого процесса нельзя — поэтому её
  // смена (человек поправил рецепт) означает смену процесса. Беседа при этом продолжается:
  // новый процесс поднимается с --resume, теряется только состояние серверов, и это честная
  // цена за новую развёртку, а не побочный эффект.
  live?.end();
  const resume = live?.conversationId ?? (await conversationOf(contextId));
  const created = await CliSession.start({ ...spec, resume });

  created.onConversation = (id) => void remember(contextId, id);
  created.onEnd = () => {
    // Убирается только собственная запись: на месте умершего процесса уже мог встать новый.
    if (sessions.get(contextId) === created) sessions.delete(contextId);
  };
  sessions.set(contextId, created);
  return created;
}

/**
 * Отдать CLI задачу и дождаться ответа.
 *
 * Ошибка возвращается значением, а не броском: неудача прогона — обычное дело, и вызывающий
 * обязан рассказать о ней человеку словами, а не поймать исключение.
 */
export async function run(
  request: RunRequest,
  signal?: AbortSignal,
  onStep?: OnStep,
): Promise<RunResult> {
  const spec = { systemPrompt: request.systemPrompt, mcpServers: request.mcpServers };

  // Без контекста беседы процессу незачем жить дольше одного хода.
  const session = request.contextId
    ? await sessionFor(request.contextId, spec)
    : await CliSession.start(spec);

  try {
    const outcome = await session.turn(request.prompt, signal, onStep);
    if ("failed" in outcome) {
      return { ok: false, text: outcome.failed };
    }

    const done = outcome.done;
    return {
      // Признак неудачи берётся из итога: CLI не завершается и не меняет код возврата, когда
      // не удался сам прогон, — он честно присылает отчёт с ошибкой.
      ok: done.ok,
      text: done.text || (done.ok ? "" : session.errorTail() || "прогон не удался, причину CLI не назвал"),
      usage: usageOf(done.report),
      conversationId: done.conversationId,
    };
  } finally {
    if (!request.contextId) {
      session.end();
    }
  }
}
