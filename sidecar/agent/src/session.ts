/**
 * Долгоживущий процесс CLI на сессию.
 *
 * Раньше на каждое сообщение поднимался новый процесс, и вместе с ним умирали соединения с
 * MCP: сервер, державший состояние между вызовами (вкладку браузера, например), на следующем
 * сообщении отдавал пустоту, а агент этого не замечал — он помнил, что уже открывал. Причина
 * в жизни процесса, поэтому чинится она здесь: процесс живёт, сообщения приходят потоком
 * через `--input-format stream-json`, и каждое заканчивается своим итоговым отчётом.
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { lines, type Step, stepsOf } from "./stream.js";

export type OnStep = (step: Step) => void;

/** Чем один процесс отличается от другого: развёртка целиком уходит в аргументы запуска. */
export interface SessionSpec {
  systemPrompt?: string;
  mcpServers?: Record<string, unknown>;
  /** Беседа CLI, которую процесс продолжает, если она уже заводилась. */
  resume?: string;
}

/** Итог хода: отчёт CLI, либо причина, по которой отчёта не будет. */
export type TurnResult = { done: Extract<Step, { kind: "done" }> } | { failed: string };

/**
 * Отпечаток развёртки. Развёртка задаётся при старте процесса и сменить её на живом нельзя —
 * поэтому её смена означает смену процесса, и сравниваются они вот этим.
 */
export function fingerprintOf(spec: Pick<SessionSpec, "systemPrompt" | "mcpServers">): string {
  return JSON.stringify({
    systemPrompt: spec.systemPrompt ?? "",
    mcpServers: spec.mcpServers ?? {},
  });
}

// Простой без работы процесс гасится: у машины несколько гигабайт на всех соседей, и десяток
// забытых процессов с браузерами съел бы её. Беседа при этом не теряется — следующий ход
// поднимет процесс заново с --resume; теряется только состояние MCP-серверов, что после долгой
// паузы честнее, чем держать его вечно. Ноль выключает гашение осознанно; пустая или
// нечитаемая переменная — это «не задано», а не ноль: незаполненный компоуз не должен молча
// делать процессы вечными.
const IDLE_MS = (() => {
  const raw = Number(process.env["AGENT_SESSION_IDLE_MS"] || NaN);
  return Number.isFinite(raw) ? raw : 30 * 60 * 1000;
})();

// Сколько ждать после просьбы остановиться, прежде чем убить процесс.
const GRACE_MS = 10_000;

interface Turn {
  onStep?: OnStep;
  settle: (result: TurnResult) => void;
}

export class CliSession {
  readonly fingerprint: string;

  /** Идентификатор беседы, который CLI назначил себе сам; обновляется по его же событиям. */
  conversationId?: string;
  onConversation?: (id: string) => void;
  onEnd?: () => void;

  private readonly child: ChildProcessWithoutNullStreams;
  private readonly workDir?: string;
  private queue: Promise<unknown> = Promise.resolve();
  private current?: Turn;
  private err = "";
  private idle?: NodeJS.Timeout;
  /** Новые ходы больше не принимаются: процесс гасится или уже погашен. */
  private ended = false;
  /** Процесс завершился, всё прибрано. */
  private closed = false;

  /** Процесс поднимается один раз на сессию; конфиг серверов живёт файлом столько же. */
  static async start(spec: SessionSpec): Promise<CliSession> {
    // -p без текста задачи: задачи приходят потоком через stdin, по объекту на строку.
    // Отчёт объектами, а не голым текстом: только так наружу доезжают расход и признак
    // неудачи, причём по каждому ходу отдельно.
    const args = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"];

    // Беседа продолжается по идентификатору, который CLI назначил себе сам. Своего мы ему не
    // навязываем: назначенный нами однажды окажется занятым, и запуск упадёт на ровном месте.
    if (spec.resume) {
      args.push("--resume", spec.resume);
    }

    if (spec.systemPrompt) {
      args.push("--system-prompt", spec.systemPrompt);
    }

    // Конфиг серверов передаётся файлом, а не строкой в аргументах: список тулзов бывает
    // длинным, а у командной строки есть предел, за которым запуск падает без внятной причины.
    let workDir: string | undefined;
    if (spec.mcpServers && Object.keys(spec.mcpServers).length > 0) {
      workDir = await mkdtemp(join(tmpdir(), "neurobox-mcp-"));
      const configPath = join(workDir, "mcp.json");
      await writeFile(configPath, JSON.stringify({ mcpServers: spec.mcpServers }), "utf8");
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
      for (const name of Object.keys(spec.mcpServers)) {
        args.push("--allowedTools", `mcp__${name}__*`);
      }
    }

    const child = spawn("claude", args, { stdio: ["pipe", "pipe", "pipe"] });
    return new CliSession(child, fingerprintOf(spec), workDir);
  }

  private constructor(child: ChildProcessWithoutNullStreams, fingerprint: string, workDir?: string) {
    this.child = child;
    this.fingerprint = fingerprint;
    this.workDir = workDir;

    const split = lines();
    child.stdout.on("data", (chunk) => {
      for (const event of split(String(chunk))) {
        for (const step of stepsOf(event)) {
          this.take(step);
        }
      }
    });

    // У долгоживущего процесса stderr копится бесконечно, а для причины отказа нужен конец,
    // а не история — поэтому хранится только хвост.
    child.stderr.on("data", (chunk) => {
      this.err = (this.err + String(chunk)).slice(-4000);
    });

    // Вход может закрыться раньше, чем сюда перестанут писать; без слушателя эта ошибка
    // уронила бы процесс адаптера целиком.
    child.stdin.on("error", () => undefined);

    child.on("error", (error) => this.close(`не удалось запустить claude: ${error.message}`));
    child.on("close", (code) => this.close(this.err.trim() || `процесс агента завершился, код ${code}`));
  }

  /** Процесс жив и готов принимать ходы. */
  get alive(): boolean {
    return !this.ended;
  }

  /** Хвост stderr — единственная причина, которую CLI называет при молчаливом провале. */
  errorTail(): string {
    return this.err.trim();
  }

  /**
   * Отдать процессу задачу и дождаться её итога.
   *
   * Ходы строго по одному: у процесса одна беседа, и параллельные сообщения в ней
   * перемешались бы. Очередь — цепочка обещаний; упавший ход её не рвёт.
   */
  turn(prompt: string, signal?: AbortSignal, onStep?: OnStep): Promise<TurnResult> {
    const result = this.queue.then(() => this.oneTurn(prompt, signal, onStep));
    this.queue = result.catch(() => undefined);
    return result;
  }

  /** Погасить процесс вежливо: закрытый вход для CLI — сигнал завершиться. */
  end(): void {
    if (this.ended) return;
    this.ended = true;
    clearTimeout(this.idle);
    try {
      this.child.stdin.end();
    } catch {
      // Вход уже закрыт — процесс и так умирает.
    }
    // Вежливость с пределом: не закрылся сам — будет закрыт.
    const killer = setTimeout(() => this.child.kill("SIGKILL"), GRACE_MS);
    killer.unref();
    this.child.once("close", () => clearTimeout(killer));
  }

  private oneTurn(prompt: string, signal?: AbortSignal, onStep?: OnStep): Promise<TurnResult> {
    if (this.ended) {
      return Promise.resolve({ failed: this.errorTail() || "процесс агента уже остановлен" });
    }
    if (signal?.aborted) {
      return Promise.resolve({ failed: "прогон отменён до запуска" });
    }

    clearTimeout(this.idle);

    return new Promise((resolve) => {
      const turn: Turn = {
        onStep,
        settle: (outcome) => {
          signal?.removeEventListener("abort", onAbort);
          resolve(outcome);
        },
      };

      const onAbort = (): void => {
        // Просьба остановиться, а не удар по процессу: с процессом умерли бы соединения MCP,
        // ради которых он и живёт. CLI понимает управляющий запрос в том же входном потоке.
        this.write({
          type: "control_request",
          request_id: crypto.randomUUID(),
          request: { subtype: "interrupt" },
        });
        // Не понял или завис — процесс убивается. Беседа это переживёт: следующий ход
        // поднимет новый процесс с --resume, потеряв только состояние серверов.
        const killer = setTimeout(() => {
          if (this.current === turn) this.child.kill("SIGKILL");
        }, GRACE_MS);
        killer.unref();
      };

      this.current = turn;
      signal?.addEventListener("abort", onAbort, { once: true });

      const sent = this.write({
        type: "user",
        message: { role: "user", content: [{ type: "text", text: prompt }] },
      });
      if (!sent) {
        this.current = undefined;
        turn.settle({ failed: this.errorTail() || "вход процесса агента закрыт" });
      }
    });
  }

  private take(step: Step): void {
    if ((step.kind === "started" || step.kind === "done") && step.conversationId) {
      this.conversationId = step.conversationId;
      this.onConversation?.(step.conversationId);
    }

    this.current?.onStep?.(step);

    if (step.kind === "done") {
      const turn = this.current;
      this.current = undefined;
      this.rest();
      turn?.settle({ done: step });
    }
  }

  private write(payload: Record<string, unknown>): boolean {
    if (!this.child.stdin.writable) return false;
    try {
      this.child.stdin.write(JSON.stringify(payload) + "\n");
      return true;
    } catch {
      return false;
    }
  }

  private rest(): void {
    clearTimeout(this.idle);
    if (IDLE_MS <= 0) return;
    this.idle = setTimeout(() => this.end(), IDLE_MS);
    this.idle.unref();
  }

  private close(reason: string): void {
    if (this.closed) return;
    this.closed = true;
    this.ended = true;
    clearTimeout(this.idle);

    const turn = this.current;
    this.current = undefined;
    turn?.settle({ failed: reason });

    if (this.workDir) {
      void rm(this.workDir, { recursive: true, force: true });
    }
    this.onEnd?.();
  }
}
