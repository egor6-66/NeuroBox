/** Единственная страница пульта: слева разговоры, справа текущий. */

import { createResource, createSignal, Show } from "solid-js";

import { api } from "#/shared/api/client";
import { Chat } from "#/widgets/chat";
import { NewSession } from "#/widgets/new-session";
import { SessionList } from "#/widgets/session-list";

export function Console() {
  const [current, setCurrent] = createSignal<string | null>(null);
  const [sessions, { refetch }] = createResource(() => api.sessions());

  const picked = () => (sessions() ?? []).find((s) => s.id === current()) ?? null;

  const opened = async (id: string): Promise<void> => {
    await refetch();
    setCurrent(id);
  };

  return (
    <div class="layout">
      <aside class="side">
        <header>
          <span class="brand">NeuroBox</span>
          <NewSession onCreated={(id) => void opened(id)} />
        </header>
        <SessionList
          sessions={sessions() ?? []}
          current={current()}
          onPick={setCurrent}
        />
      </aside>

      <Show
        when={picked()}
        fallback={
          <div class="empty">
            Выберите разговор слева или заведите новый.
          </div>
        }
      >
        {(session) => <Chat session={session()} />}
      </Show>
    </div>
  );
}
