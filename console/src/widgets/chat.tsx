/** Разговор: история, ход текущего прогона, отправка и отмена. */

import { createEffect, createSignal, For, onCleanup, Show } from "solid-js";

import { type Live, openSession } from "#/entities/session/model";
import type { Session } from "#/shared/api/client";

interface Props {
  session: Session;
}

export function Chat(props: Props) {
  const [live, setLive] = createSignal<Live | null>(null);
  const [draft, setDraft] = createSignal("");
  let thread: HTMLDivElement | undefined;

  // Разговор переоткрывается при смене сессии, и старый закрывается: без этого каждый переход
  // оставлял бы за собой открытый поток событий.
  createEffect(() => {
    const opened = openSession(props.session.id);
    setLive((previous) => {
      previous?.dispose();
      return opened;
    });
    onCleanup(() => opened.dispose());
  });

  // Лента прокручивается к свежему: иначе ответ приходит за нижним краем и выглядит как
  // отсутствие ответа.
  createEffect(() => {
    live()?.messages();
    live()?.steps();
    queueMicrotask(() => thread?.scrollTo({ top: thread.scrollHeight }));
  });

  const send = (): void => {
    const text = draft().trim();
    if (!text || live()?.running()) return;
    setDraft("");
    void live()?.say(text);
  };

  return (
    <section class="chat">
      <header>
        <div>
          <div class="brand">{props.session.title ?? "Без названия"}</div>
          <div class="hint">
            {props.session.recipe} · {props.session.passport} · {props.session.agent}
          </div>
        </div>
      </header>

      <div class="thread" ref={thread}>
        <For each={live()?.messages() ?? []}>
          {(message) => (
            <article class={`turn ${message.author}`}>
              <span class="who">{message.author === "human" ? "вы" : "агент"}</span>
              <div class="body">{message.text}</div>
            </article>
          )}
        </For>

        <Show when={(live()?.steps() ?? []).length > 0}>
          <div class="steps">
            <span class="head">агент работает</span>
            <For each={live()?.steps() ?? []}>{(step) => <span>{step}</span>}</For>
          </div>
        </Show>

        <Show when={(live()?.notes() ?? []).length > 0}>
          <div class="notes">
            <span class="head">агент сообщил о затыках</span>
            <For each={live()?.notes() ?? []}>
              {(note) => (
                <article class="note">
                  <p>{note.what}</p>
                  <Show when={note.where}>{(place) => <small>где: {place()}</small>}</Show>
                  <Show when={note.workaround}>
                    {(how) => <small>обошёл: {how()}</small>}
                  </Show>
                </article>
              )}
            </For>
          </div>
        </Show>

        <Show when={live()?.failure()}>
          {(means) => (
            <div class="steps bad">
              <span class="head">не получилось</span>
              <span>{means()}</span>
            </div>
          )}
        </Show>
      </div>

      <div class="compose">
        <textarea
          value={draft()}
          placeholder="Что сделать?"
          onInput={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => {
            // Отправка по Ctrl+Enter, а не по Enter: реплики бывают многострочными, и
            // отправка на первом переносе строки ломала бы половину из них.
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div class="row">
          <span class="hint">Ctrl+Enter — отправить</span>
          <Show
            when={live()?.running()}
            fallback={
              <button class="primary" disabled={!draft().trim()} onClick={send}>
                Отправить
              </button>
            }
          >
            <button onClick={() => void live()?.cancel()}>Прервать</button>
          </Show>
        </div>
      </div>
    </section>
  );
}
