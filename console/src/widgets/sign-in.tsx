/**
 * Вход.
 *
 * Два поля: логин — чьим именем работать (сессии живут по владельцам), токен — можно ли сюда
 * вообще. Логин сервис не проверяет, и это названо честно: настоящий вход придёт с общим
 * модулем авторизации, а место для него уже готово — всё остальное про вход не знает.
 */

import { createSignal, Show } from "solid-js";

import { api, login, ServiceError, token } from "#/shared/api/client";

interface Props {
  onEntered: () => void;
}

export function SignIn(props: Props) {
  const [name, setName] = createSignal(login.get());
  const [secret, setSecret] = createSignal("");
  const [failure, setFailure] = createSignal<string | null>(null);
  const [busy, setBusy] = createSignal(false);

  const ready = (): boolean => Boolean(name().trim()) && Boolean(secret().trim());

  const enter = async (): Promise<void> => {
    if (!ready()) return;

    setBusy(true);
    setFailure(null);
    login.set(name().trim());
    token.set(secret().trim());
    try {
      // Проверяем сразу, а не откладываем до первой ручки: иначе человек попадает внутрь и
      // упирается в отказ там, где уже не понимает, при чём тут вход.
      await api.recipes();
      props.onEntered();
    } catch (error) {
      token.set("");
      setFailure(
        error instanceof ServiceError && error.status === 401
          ? "Не подошло: сервис не пустил с этими логином и токеном."
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
        <p class="hint">Логин — чьим именем работать, токен — доступ. Латиницей.</p>

        <div class="field">
          <label for="login">Логин</label>
          <input
            id="login"
            type="text"
            autocomplete="username"
            value={name()}
            onInput={(e) => setName(e.currentTarget.value)}
          />
        </div>

        <div class="field">
          <label for="token">Токен</label>
          <input
            id="token"
            type="password"
            autocomplete="current-password"
            value={secret()}
            onInput={(e) => setSecret(e.currentTarget.value)}
          />
        </div>

        <Show when={failure()}>{(text) => <p class="bad">{text()}</p>}</Show>

        <div class="row">
          <button class="primary" type="submit" disabled={busy() || !ready()}>
            {busy() ? "Проверяю…" : "Войти"}
          </button>
        </div>
      </form>
    </div>
  );
}
