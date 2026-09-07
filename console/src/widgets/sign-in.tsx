/**
 * Вход.
 *
 * Пока это одно поле с общим токеном — точка входа одна, и большего честно не нужно. Когда
 * появится общий модуль авторизации, здесь окажется обычный вход, а не переделка: место уже
 * есть, и всё остальное про него не знает.
 */

import { createSignal, Show } from "solid-js";

import { api, ServiceError, token } from "#/shared/api/client";

interface Props {
  onEntered: () => void;
}

export function SignIn(props: Props) {
  const [value, setValue] = createSignal("");
  const [failure, setFailure] = createSignal<string | null>(null);
  const [busy, setBusy] = createSignal(false);

  const enter = async (): Promise<void> => {
    const given = value().trim();
    if (!given) return;

    setBusy(true);
    setFailure(null);
    token.set(given);
    try {
      // Проверяем сразу, а не откладываем до первой ручки: иначе человек попадает внутрь и
      // упирается в отказ там, где уже не понимает, при чём тут вход.
      await api.recipes();
      props.onEntered();
    } catch (error) {
      token.set("");
      setFailure(
        error instanceof ServiceError && error.status === 401
          ? "Токен не подошёл."
          : error instanceof ServiceError
            ? error.message
            : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div class="gate">
      <form
        class="card"
        onSubmit={(e) => {
          e.preventDefault();
          void enter();
        }}
      >
        <h2>NeuroBox</h2>
        <p class="hint">Введите токен доступа.</p>

        <div class="field">
          <label for="token">Токен</label>
          <input
            id="token"
            type="password"
            autocomplete="current-password"
            value={value()}
            onInput={(e) => setValue(e.currentTarget.value)}
          />
        </div>

        <Show when={failure()}>{(text) => <p class="bad">{text()}</p>}</Show>

        <div class="row">
          <button class="primary" type="submit" disabled={busy() || !value().trim()}>
            {busy() ? "Проверяю…" : "Войти"}
          </button>
        </div>
      </form>
    </div>
  );
}
