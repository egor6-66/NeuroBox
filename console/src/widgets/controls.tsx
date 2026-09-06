/**
 * Левая колонка контроллера: сверху агент, под ним ручки серверов.
 *
 * Агент — такой же элемент списка, но всегда первый: он не один из инструментов, он тот, кто
 * ими распоряжается, и место у него постоянное, чтобы не искать его среди тридцати ручек.
 */

import { For, Show } from "solid-js";

import type { Server } from "#/shared/api/client";

export type Picked = { what: "agent" } | { what: "tool"; seed: string; tool: string };

interface Props {
  servers: Server[];
  picked: Picked;
  onPick: (picked: Picked) => void;
  onRefresh: () => void;
}

export function Controls(props: Props) {
  const chosen = (seed: string, tool: string): boolean =>
    props.picked.what === "tool" && props.picked.seed === seed && props.picked.tool === tool;

  return (
    <div class="sessions">
      <button
        class="session agent"
        aria-current={props.picked.what === "agent"}
        onClick={() => props.onPick({ what: "agent" })}
      >
        <span>Агент</span>
        <small>разговор, а не отдельная ручка</small>
      </button>

      <For each={props.servers}>
        {(server) => (
          <>
            <div class="group">
              <span>{server.seed}</span>
              <Show when={server.ok} fallback={<small class="bad">не отвечает</small>}>
                <small>{server.tools.length} ручек · ≈{Math.round(server.weight_chars / 4)} токенов</small>
              </Show>
            </div>

            <Show when={!server.ok}>
              <For each={server.refusals}>
                {(refusal) => <p class="hint bad">{refusal.means}</p>}
              </For>
            </Show>

            <For each={server.tools}>
              {(tool) => (
                <button
                  class="session"
                  aria-current={chosen(server.seed, tool.name)}
                  onClick={() =>
                    props.onPick({ what: "tool", seed: server.seed, tool: tool.name })
                  }
                >
                  <span>{tool.name}</span>
                  <Show when={tool.description}>
                    {(text) => <small>{text().split("\n")[0]}</small>}
                  </Show>
                </button>
              )}
            </For>
          </>
        )}
      </For>

      <Show when={props.servers.length === 0}>
        <p class="empty">
          Серверов не видно.
          <br />
          Их описания читаются опросом.
        </p>
      </Show>

      <button class="refresh" onClick={props.onRefresh}>
        Опросить серверы заново
      </button>
    </div>
  );
}
