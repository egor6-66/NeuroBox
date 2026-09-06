/**
 * Состояние одного разговора: история, ход текущего прогона, отправка и отмена.
 *
 * Живёт отдельно от вида намеренно: то, что происходит с сессией, одинаково для любого
 * оформления, и переписывать это вместе с разметкой не придётся.
 */

import { createSignal } from "solid-js";

import {
  api,
  type Message,
  type Note,
  type Run,
  type RunEvent,
  ServiceError,
  watch,
} from "#/shared/api/client";

export interface Live {
  messages: () => Message[];
  notes: () => Note[];
  steps: () => string[];
  running: () => Run | null;
  failure: () => string | null;
  say: (text: string) => Promise<void>;
  cancel: () => Promise<void>;
  dispose: () => void;
}

export function openSession(id: string): Live {
  const [messages, setMessages] = createSignal<Message[]>([]);
  const [notes, setNotes] = createSignal<Note[]>([]);
  const [steps, setSteps] = createSignal<string[]>([]);
  const [running, setRunning] = createSignal<Run | null>(null);
  const [failure, setFailure] = createSignal<string | null>(null);

  const reload = async (): Promise<void> => {
    // Заметки перечитываются вместе с историей: агент пишет их по ходу прогона, и отдельного
    // события о них нет — оно означало бы второй способ узнавать одно и то же.
    const [said, written] = await Promise.all([api.messages(id), api.notes(id)]);
    setMessages(said);
    setNotes(written);
  };

  const onEvent = (event: RunEvent): void => {
    if (event.event === "run-step" && event.text) {
      // Шаги копятся, а не заменяют друг друга: человеку важно видеть, ЧТО уже сделано, а не
      // только последнее действие.
      setSteps((was) => [...was, event.text ?? ""]);
      return;
    }

    if (event.event === "run-finished" || event.event === "run-canceled") {
      setSteps([]);
      setRunning(null);
      if (event.refusal) setFailure(event.means ?? event.refusal);
      void reload();
    }
  };

  const stop = watch(id, onEvent);
  void reload();

  return {
    messages,
    notes,
    steps,
    running,
    failure,

    say: async (text: string): Promise<void> => {
      setFailure(null);
      setSteps([]);
      // Своя реплика показывается сразу, не дожидаясь ответа сервиса: ожидание в пустом окне
      // выглядит как потерянное сообщение.
      setMessages((was) => [
        ...was,
        { author: "human", text, run_id: null, created_at: new Date().toISOString() },
      ]);
      try {
        const { run } = await api.say(id, text);
        setRunning(run);
      } catch (error) {
        setFailure(error instanceof ServiceError ? error.message : String(error));
        void reload();
      }
    },

    cancel: async (): Promise<void> => {
      const current = running();
      if (!current) return;
      try {
        await api.cancel(id, current.id);
      } catch (error) {
        setFailure(error instanceof ServiceError ? error.message : String(error));
      }
    },

    dispose: stop,
  };
}
