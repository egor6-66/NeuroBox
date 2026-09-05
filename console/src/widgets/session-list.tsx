/** Список разговоров: свежие сверху, как их отдаёт сервис. */

import { For, Show } from "solid-js";

import type { Session } from "#/shared/api/client";

interface Props {
  sessions: Session[];
  current: string | null;
  onPick: (id: string) => void;
}

export function SessionList(props: Props) {
  return (
    <div class="sessions">
      <Show
        when={props.sessions.length > 0}
        fallback={<p class="empty">Разговоров пока нет.<br />Заведите первый.</p>}
      >
        <For each={props.sessions}>
          {(session) => (
            <button
              class="session"
              aria-current={session.id === props.current}
              onClick={() => props.onPick(session.id)}
            >
              <span>{session.title ?? "Без названия"}</span>
              <small>
                {session.recipe} · {session.passport}
              </small>
            </button>
          )}
        </For>
      </Show>
    </div>
  );
}
