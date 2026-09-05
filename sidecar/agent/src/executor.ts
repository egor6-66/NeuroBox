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
    default:
      return undefined;
  }
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
          metadata: { step: step.kind },
        }),
      );
    };

    let result;
    try {
      result = await run(
        {
          prompt: textOf(userMessage.parts),
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
