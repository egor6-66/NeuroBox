/** Точка входа пульта. */

import { render } from "solid-js/web";

import { Console } from "#/pages/index";
import "#/shared/ui/styles.css";

const root = document.getElementById("root");
if (!root) {
  // Молча ничего не рисовать — худший исход: страница выглядит сломанной без причины.
  throw new Error("не найден корневой элемент #root");
}

render(() => <Console />, root);
