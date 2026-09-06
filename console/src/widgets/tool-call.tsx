/**
 * Ручной вызов инструмента.
 *
 * Нужен, чтобы проверить саму ручку отдельно от того, правильно ли ей распорядился агент:
 * иначе при поломке непонятно, кто из двоих виноват.
 *
 * Поля строятся по схеме, которую объявил сам сервер. Своего представления о том, что
 * принимает инструмент, у пульта нет — оно разъехалось бы с сервером при первом обновлении.
 */

import { createMemo, createSignal, For, Show } from "solid-js";

import { api, type Called, type JsonSchema, ServiceError, type Tool } from "#/shared/api/client";

interface Props {
  seed: string;
  tool: Tool;
}

type Values = Record<string, string>;

function kindOf(schema: JsonSchema): string {
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  return type ?? "string";
}

/**
 * Превратить введённое человеком в значение нужного вида.
 *
 * Пустое поле НЕ отправляется вовсе: пустая строка и «не указано» — разные вещи, и подставлять
 * первое вместо второго значит менять смысл запроса.
 */
function valueOf(schema: JsonSchema, raw: string): unknown {
  const text = raw.trim();
  if (!text) return undefined;

  switch (kindOf(schema)) {
    case "integer":
    case "number": {
      const parsed = Number(text);
      return Number.isFinite(parsed) ? parsed : text;
    }
    case "boolean":
      return text === "true";
    case "array":
    case "object":
      try {
        return JSON.parse(text);
      } catch {
        // Не разобралось — отправляем как есть: пусть сервер скажет, что не так, своими
        // словами. Наша догадка о его ожиданиях была бы хуже его собственного отказа.
        return text;
      }
    default:
      return text;
  }
}

export function ToolCall(props: Props) {
  const [values, setValues] = createSignal<Values>({});
  const [result, setResult] = createSignal<Called | null>(null);
  const [failure, setFailure] = createSignal<string | null>(null);
  const [busy, setBusy] = createSignal(false);

  const fields = createMemo(() => {
    // Пересчитывается при смене инструмента: иначе на новой ручке остались бы поля старой.
    const schema = props.tool.input_schema ?? {};
    const required = new Set(schema.required ?? []);
    return Object.entries(schema.properties ?? {}).map(([name, field]) => ({
      name,
      field,
      required: required.has(name),
    }));
  });

  const set = (name: string, raw: string): void => {
    setValues((was) => ({ ...was, [name]: raw }));
  };

  const run = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    setResult(null);

    const args: Record<string, unknown> = {};
    for (const { name, field } of fields()) {
      const value = valueOf(field, values()[name] ?? "");
      if (value !== undefined) args[name] = value;
    }

    try {
      setResult(await api.callTool(props.seed, props.tool.name, args));
    } catch (error) {
      setFailure(error instanceof ServiceError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const shown = createMemo(() => {
    const called = result();
    if (!called) return "";
    if (called.structured) return JSON.stringify(called.structured, null, 2);
    return called.content.map((block) => block.text ?? JSON.stringify(block)).join("\n\n");
  });

  return (
    <section class="chat">
      <header>
        <div>
          <div class="brand">{props.tool.name}</div>
          <div class="hint">{props.tool.description ?? "без описания"}</div>
        </div>
        <span class="hint">{props.seed}</span>
      </header>

      <div class="thread">
        <Show
          when={fields().length > 0}
          fallback={<p class="hint">У инструмента нет аргументов — просто вызовите его.</p>}
        >
          <For each={fields()}>
            {({ name, field, required }) => (
              <div class="field">
                <label for={`arg-${name}`}>
                  {name}
                  {required ? " · обязательное" : ""} · {kindOf(field)}
                  <Show when={field.description}>{(text) => <> — {text()}</>}</Show>
                </label>
                <Show
                  when={field.enum}
                  fallback={
                    <input
                      id={`arg-${name}`}
                      value={values()[name] ?? ""}
                      placeholder={
                        kindOf(field) === "object" || kindOf(field) === "array" ? "JSON" : ""
                      }
                      onInput={(e) => set(name, e.currentTarget.value)}
                    />
                  }
                >
                  {(options) => (
                    <select
                      id={`arg-${name}`}
                      value={values()[name] ?? ""}
                      onChange={(e) => set(name, e.currentTarget.value)}
                    >
                      <option value="">не указано</option>
                      <For each={options()}>
                        {(option) => <option value={String(option)}>{String(option)}</option>}
                      </For>
                    </select>
                  )}
                </Show>
              </div>
            )}
          </For>
        </Show>

        <Show when={failure()}>
          {(text) => (
            <div class="steps bad">
              <span class="head">не получилось</span>
              <span>{text()}</span>
            </div>
          )}
        </Show>

        <Show when={result()}>
          {(called) => (
            <div class="steps">
              <span class="head">
                {called().ok ? "ответ инструмента" : "инструмент ответил отказом"}
              </span>
              <For each={called().refusals}>
                {(refusal) => (
                  <span class="bad">
                    {refusal.name} — {refusal.means}
                  </span>
                )}
              </For>
              <Show when={shown()}>
                <pre class="result">{shown()}</pre>
              </Show>
            </div>
          )}
        </Show>
      </div>

      <div class="compose">
        <div class="row">
          <span class="hint">Вызов идёт мимо агента — проверяется сама ручка</span>
          <button class="primary" disabled={busy()} onClick={() => void run()}>
            {busy() ? "Вызываю…" : "Вызвать"}
          </button>
        </div>
      </div>
    </section>
  );
}
