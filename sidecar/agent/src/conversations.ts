/**
 * Соответствие «контекст A2A → беседа CLI».
 *
 * У CLI два несовместимых ключа: начать беседу с заданным идентификатором и продолжить
 * существующую. Каждый ошибается, если применить не к месту, а знать наверняка, заведена ли
 * беседа, может только тот, кто её заводил, — то есть адаптер.
 *
 * Раньше это решал оркестратор по своей базе, и он ошибался: отменённый прогон беседу уже
 * создал, а по его записям она выглядела несостоявшейся. Признак «был удачный прогон» и факт
 * «беседа существует» — разные вещи, и подменять второе первым нельзя.
 *
 * Идентификатор беседы не назначается нами: CLI сообщает свой собственный в отчёте, и мы
 * запоминаем именно его. Так исчезает и столкновение имён, и необходимость угадывать.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const FILE = process.env["AGENT_STATE_FILE"] ?? "/state/conversations.json";

let known: Record<string, string> | undefined;

async function load(): Promise<Record<string, string>> {
  if (known) return known;
  try {
    known = JSON.parse(await readFile(FILE, "utf8")) as Record<string, string>;
  } catch {
    // Файла нет или он испорчен — начинаем с пустого. Беседы при этом не теряются: они живут
    // у самого CLI, теряется только знание о том, какая к какому контексту относится.
    known = {};
  }
  return known;
}

/** Идентификатор беседы CLI для контекста, если она уже заводилась. */
export async function conversationOf(contextId: string): Promise<string | undefined> {
  return (await load())[contextId];
}

/** Запомнить беседу, которую CLI завёл сам. */
export async function remember(contextId: string, conversationId: string): Promise<void> {
  const map = await load();
  if (map[contextId] === conversationId) return;

  map[contextId] = conversationId;

  try {
    await mkdir(dirname(FILE), { recursive: true });
    // Пишем сразу, а не при остановке: контейнер редко останавливают вежливо, и отложенная
    // запись означала бы потерянную память ровно в тот момент, когда она нужна.
    await writeFile(FILE, JSON.stringify(map), "utf8");
  } catch (error) {
    // Незаписанная заметка — УХУДШЕНИЕ, а не провал: прогон удался, в памяти процесса связь
    // осталась, и разговор продолжится. Потеряется он только при перезапуске адаптера.
    // Ронять из-за этого удавшуюся работу было бы хуже ошибки, которую мы чиним.
    // Молчать тоже нельзя, поэтому причина уходит в поток ошибок.
    console.error(`[conversations] заметка не сохранена: ${String(error)}`);
  }
}

/** Забыть всё — для тестов. */
export function forget(): void {
  known = undefined;
}
