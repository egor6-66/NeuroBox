/** Точка входа пульта. */

import { createSignal, Show } from "solid-js";
import { render } from "solid-js/web";

import { Console } from "#/pages/index";
import { api, login, ServiceError, token } from "#/shared/api/client";
import { SignIn } from "#/widgets/sign-in";
import "#/shared/ui/styles.css";

function Root() {
  // Три состояния, а не два: пока не спросили сервис, неизвестно, нужен ли вход вообще —
  // в разработке его нет. Показать форму раньше времени значило бы требовать токен там, где
  // он не нужен.
  const [entered, setEntered] = createSignal<boolean | null>(null);

  void api
    .recipes()
    .then(() => setEntered(true))
    .catch((error) => setEntered(error instanceof ServiceError && error.status === 401 ? false : true));

  return (
    <Show when={entered() !== null} fallback={<div class="empty">…</div>}>
      <Show when={entered()} fallback={<SignIn onEntered={() => setEntered(true)} />}>
        <Console onLeave={() => {
          token.set("");
          login.set("");
          setEntered(false);
        }} />
      </Show>
    </Show>
  );
}

const root = document.getElementById("root");
if (!root) {
  // Молча ничего не рисовать — худший исход: страница выглядит сломанной без причины.
  throw new Error("не найден корневой элемент #root");
}

render(() => <Root />, root);
