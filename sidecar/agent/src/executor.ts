/**
 * Исполнитель задач A2A. Переводит задачу протокола в запуск CLI и обратно.
 *
 * Ничего не решает про содержание: инструкцию и серверы присылает оркестратор, здесь только
 * доставка. Это и есть смысл границы — снаружи протокол, внутри чужой инструмент.
 */

import {
  AgentEvent,
  type AgentExecutor,
  type ExecutionEventBus,
  type RequestContext,
} from "@a2a-js/sdk/server";
import { Role, type Task, TaskState, type TaskStatusUpdateEvent } from "@a2a-js/sdk";

import { run } from "./claude.js";
import type { Step } from "./stream.js";

/** Метаданные, которыми оркестратор передаёт развёртку. Имена наши, протоколу безразличны. */
interface Unfolded {
  systemPrompt?: string;
  mcpServers?: Record<string, unknown>;
  context?: Record<string, string>;
}

/**
 * Приклеить к реплике то, что приложение знает о месте, откуда она пришла.
 *
 * Отдельным блоком с явной подписью, а не строкой перед текстом: без границы агент не отличит
 * данные приложения от слов человека и начнёт на них отвечать — «да, вижу, вы на кнопке».
 *
 * Содержимое не разбирается: про компоненты знает тот, кто их показывает. Мы отвечаем только за
 * то, чтобы это доехало помеченным.
 */
function withContext(text: string, context?: Record<string, string>): string {
  const pairs = Object.entries(context ?? {}).filter(([key]) => key.trim());
  if (!pairs.length) return text;

  const lines = pairs.map(([key, value]) => `${key}: ${value}`).join("\n");
  return [
    "<контекст>",
    "Это данные приложения о том, где находится человек. Не реплика и не просьба —",
    "отвечать на них не нужно, отвечай на реплику ниже.",
    lines,
    "</контекст>",
    "",
    text,
  ].join("\n");
}

function textOf(parts: readonly { content?: unknown }[]): string {
  const chunks: string[] = [];
  for (const part of parts) {
    const content = part.content as { $case?: string; value?: unknown } | undefined;
    if (content?.$case === "text" && typeof content.value === "string") {
      chunks.push(content.value);
    }
  }
  return chunks.join("\n").trim();
}

/** Человеческое описание шага: его читает человек в пульте, а не машина. */
function describe(step: Step): string | undefined {
  switch (step.kind) {
    case "started":
      return step.servers.length
        ? `подключено инструментов: ${step.tools} (серверы: ${step.servers.join(", ")})`
        : `подключено инструментов: ${step.tools}`;
    case "said":
      return step.text;
    case "using":
      return `зовёт инструмент ${step.tool}`;
    case "result":
      // Пустой результат тоже событие: «ручка ответила ничем» и «ручка не отвечала» — разные
      // вещи, и различить их снаружи можно только если о первом сказали.
      return step.text || (step.failed ? "отказ без текста" : "пусто");
    default:
      return undefined;
  }
}

/**
 * Что уезжает о шаге, кроме его текста.
 *
 * Имя ручки и аргументы — у вызова; идентификатор вызова и признак отказа — у результата. По
 * идентификатору снаружи связывают одно с другим: в одном ходу вызовов бывает несколько, и без
 * него результат не приписать к своей просьбе.
 */
function metaOf(step: Step): Record<string, unknown> {
  if (step.kind === "using") {
    return { step: step.kind, tool: step.tool, arguments: step.input ?? {} };
  }
  if (step.kind === "result") {
    return { step: step.kind, toolCallId: step.toolCallId, failed: step.failed };
  }
  return { step: step.kind };
}

function message(taskId: string, contextId: string, text: string, usage?: unknown) {
  return {
    role: Role.ROLE_AGENT,
    messageId: crypto.randomUUID(),
    parts: [
      {
        content: { $case: "text" as const, value: text },
        metadata: undefined,
        filename: "",
        mediaType: "text/plain",
      },
    ],
    taskId,
    contextId,
    extensions: [],
    // Расход едет метаданными реплики: у статуса задачи своего места под него нет, а
    // придумывать поле мимо протокола значило бы, что его никто, кроме нас, не прочтёт.
    metadata: usage ? { usage } : {},
    referenceTaskIds: [],
  };
}

export class ClaudeExecutor implements AgentExecutor {
  private readonly cancelled = new Map<string, AbortController>();

  cancelTask = async (taskId: string): Promise<void> => {
    // Отмена доводится до самого процесса, а не только помечается флагом: помеченная, но
    // работающая задача продолжала бы тратить время и деньги уже никому не нужным ответом.
    this.cancelled.get(taskId)?.abort();
  };

  async execute(context: RequestContext, bus: ExecutionEventBus): Promise<void> {
    const { taskId, contextId, userMessage } = context;

    // Поля типов протокола не опциональные: пустое значение задаётся явно. Так в событии
    // всегда видно, что поле пусто намеренно, а не потерялось по дороге.
    const snapshot: Task = context.task ?? {
      id: taskId,
      contextId,
      status: {
        state: TaskState.TASK_STATE_SUBMITTED,
        message: undefined,
        timestamp: new Date().toISOString(),
      },
      artifacts: [],
      history: [userMessage],
      metadata: userMessage.metadata,
    };
    bus.publish(AgentEvent.task(snapshot));

    // Признака «последнее событие» в протоколе нет: терминальность выводится из состояния
    // задачи. Отдельный флаг мог бы разойтись с состоянием и соврать клиенту.
    const working: TaskStatusUpdateEvent = {
      taskId,
      contextId,
      status: {
        state: TaskState.TASK_STATE_WORKING,
        message: undefined,
        timestamp: new Date().toISOString(),
      },
      metadata: {},
    };
    bus.publish(AgentEvent.statusUpdate(working));

    const unfolded = (userMessage.metadata ?? {}) as Unfolded;
    const controller = new AbortController();
    this.cancelled.set(taskId, controller);

    // Ход дела уезжает теми же событиями состояния, что и итог: у протокола для этого уже есть
    // место, и заводить рядом своё значило бы, что его никто, кроме нас, не прочтёт.
    const onStep = (step: Step): void => {
      const said = describe(step);
      if (!said) return;
      bus.publish(
        AgentEvent.statusUpdate({
          taskId,
          contextId,
          status: {
            state: TaskState.TASK_STATE_WORKING,
            message: message(taskId, contextId, said),
            timestamp: new Date().toISOString(),
          },
          // Кроме вида шага уезжает и то, ЧЕМ агент воспользовался: снаружи по этому видно,
          // что изменилось и что стоит перезапросить.
          metadata: metaOf(step),
        }),
      );
    };

    let result;
    try {
      result = await run(
        {
          prompt: withContext(textOf(userMessage.parts), unfolded.context),
          systemPrompt: unfolded.systemPrompt,
          mcpServers: unfolded.mcpServers,
          contextId,
        },
        controller.signal,
        onStep,
      );
    } finally {
      this.cancelled.delete(taskId);
    }

    const done: TaskStatusUpdateEvent = {
      taskId,
      contextId,
      status: {
        // Провал прогона — законное состояние задачи, а не сбой протокола: клиент обязан
        // увидеть причину, а не пятисотую ошибку без объяснений.
        state: result.ok ? TaskState.TASK_STATE_COMPLETED : TaskState.TASK_STATE_FAILED,
        message: message(taskId, contextId, result.text, result.usage),
        timestamp: new Date().toISOString(),
      },
      metadata: {},
    };
    bus.publish(AgentEvent.statusUpdate(done));
    bus.finished();
  }
}
