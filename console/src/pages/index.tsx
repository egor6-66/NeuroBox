/** Контроллер бокса: слева агент и ручки, в центре — разговор или вызов инструмента. */

import { createMemo, createResource, createSignal, Show } from "solid-js";

import { api } from "#/shared/api/client";
import { Chat } from "#/widgets/chat";
import { Controls, type Picked } from "#/widgets/controls";
import { NewSession } from "#/widgets/new-session";
import { ToolCall } from "#/widgets/tool-call";

export function Console() {
  const [picked, setPicked] = createSignal<Picked>({ what: "agent" });
  // Опрос при первом открытии, если реестр пуст: он живёт в памяти сервиса и обнуляется его
  // перезапуском, а пустой список ручек выглядит как «серверов нет» — то есть как поломка.
  const [servers, { refetch: reprobe }] = createResource(async () => {
    const known = await api.servers();
    return known.length > 0 ? known : await api.probeServers();
  });
  const [sessions, { refetch: resessions }] = createResource(() => api.sessions());
  const [current, setCurrent] = createSignal<string | null>(null);

  // Разговор по умолчанию — самый свежий: контроллер открывают, чтобы продолжить работу, а не
  // чтобы каждый раз выбирать из списка.
  const session = createMemo(() => {
    const all = sessions() ?? [];
    return all.find((s) => s.id === current()) ?? all[0] ?? null;
  });

  const tool = createMemo(() => {
    const choice = picked();
    if (choice.what !== "tool") return null;
    const server = (servers() ?? []).find((s) => s.seed === choice.seed);
    const found = server?.tools.find((t) => t.name === choice.tool);
    return found && server ? { seed: server.seed, tool: found } : null;
  });

  const refresh = (): void => {
    // Опрос, а не перечитывание запомненного: сервер мог обновиться, и список ручек у него
    // теперь другой.
    void api.probeServers().then(() => reprobe());
  };

  return (
    <div class="layout">
      <aside class="side">
        <header>
          <span class="brand">NeuroBox</span>
          <NewSession
            onCreated={async (id) => {
              await resessions();
              setCurrent(id);
              setPicked({ what: "agent" });
            }}
          />
        </header>
        <Controls
          servers={servers() ?? []}
          picked={picked()}
          onPick={setPicked}
          onRefresh={refresh}
        />
      </aside>

      <Show
        when={picked().what === "agent"}
        fallback={
          <Show
            when={tool()}
            fallback={<div class="empty">Инструмент не найден — возможно, сервер обновился.</div>}
          >
            {(chosen) => <ToolCall seed={chosen().seed} tool={chosen().tool} />}
          </Show>
        }
      >
        <Show
          when={session()}
          fallback={
            <div class="empty">
              Разговоров пока нет.
              <br />
              Заведите первый — кнопкой сверху.
            </div>
          }
        >
          {(open) => <Chat session={open()} />}
        </Show>
      </Show>
    </div>
  );
}
