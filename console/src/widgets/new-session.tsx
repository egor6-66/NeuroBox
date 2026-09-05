/** Заведение разговора: чем думать, с чем работать и кто выполняет. */

import { Dialog } from "@kobalte/core/dialog";
import { createResource, createSignal, For, Show } from "solid-js";

import { api, ServiceError } from "#/shared/api/client";

interface Props {
  onCreated: (id: string) => void;
}

export function NewSession(props: Props) {
  const [open, setOpen] = createSignal(false);
  const [failure, setFailure] = createSignal<string | null>(null);

  // Каталог читается при открытии окна: он меняется правкой файлов на диске, и запомненный
  // однажды список показывал бы устаревшее.
  const [recipes] = createResource(open, () => api.recipes());
  const [passports] = createResource(open, () => api.passports());
  const [agents] = createResource(open, () => api.agents());

  const [recipe, setRecipe] = createSignal("");
  const [passport, setPassport] = createSignal("");
  const [agent, setAgent] = createSignal("");
  const [title, setTitle] = createSignal("");

  const ready = () => Boolean(recipe() && passport() && agent());

  const create = async (): Promise<void> => {
    setFailure(null);
    try {
      const session = await api.createSession({
        recipe: recipe(),
        passport: passport(),
        agent: agent(),
        title: title().trim() || undefined,
      });
      setOpen(false);
      props.onCreated(session.id);
    } catch (error) {
      setFailure(error instanceof ServiceError ? error.message : String(error));
    }
  };

  return (
    <Dialog open={open()} onOpenChange={setOpen}>
      <Dialog.Trigger as="button" class="primary">
        Новый разговор
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay class="dialog-backdrop" />
        <div class="dialog">
          <Dialog.Content class="card">
            <Dialog.Title as="h2">Новый разговор</Dialog.Title>

            <div class="field">
              <label for="recipe">Рецепт — с чем работает</label>
              <select id="recipe" value={recipe()} onChange={(e) => setRecipe(e.currentTarget.value)}>
                <option value="">выбрать…</option>
                <For each={recipes() ?? []}>
                  {(item) => <option value={item.name}>{item.name}</option>}
                </For>
              </select>
            </div>

            <div class="field">
              <label for="passport">Паспорт — чем думает</label>
              <select
                id="passport"
                value={passport()}
                onChange={(e) => setPassport(e.currentTarget.value)}
              >
                <option value="">выбрать…</option>
                <For each={passports() ?? []}>
                  {(item) => (
                    <option value={item.name}>
                      {item.name} · {item.model}
                    </option>
                  )}
                </For>
              </select>
            </div>

            <div class="field">
              <label for="agent">Агент — кто выполняет</label>
              <select id="agent" value={agent()} onChange={(e) => setAgent(e.currentTarget.value)}>
                <option value="">выбрать…</option>
                <For each={agents() ?? []}>
                  {(item) => <option value={item.agent}>{item.agent}</option>}
                </For>
              </select>
              <Show when={(agents() ?? []).length === 0}>
                <span class="hint">
                  Агентов пока не видно — их визитки читаются опросом, попробуйте обновить.
                </span>
              </Show>
            </div>

            <div class="field">
              <label for="title">Название, если нужно</label>
              <input id="title" value={title()} onInput={(e) => setTitle(e.currentTarget.value)} />
            </div>

            <Show when={failure()}>
              {(text) => <p class="bad">{text()}</p>}
            </Show>

            <div class="row">
              <Dialog.CloseButton as="button">Отмена</Dialog.CloseButton>
              <button class="primary" disabled={!ready()} onClick={() => void create()}>
                Завести
              </button>
            </div>
          </Dialog.Content>
        </div>
      </Dialog.Portal>
    </Dialog>
  );
}
