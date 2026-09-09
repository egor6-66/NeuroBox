/**
 * Разбор потока событий CLI.
 *
 * В потоковом режиме CLI пишет по объекту на строку, и из них видно, что происходит прямо
 * сейчас: какие инструменты подключились, что агент говорит, какой инструмент зовёт. Итоговый
 * отчёт приходит последним и несёт расход.
 *
 * Здесь только перевод чужих событий в наши. Ничего не решается и никуда не ходится — это
 * граница, и чем она тоньше, тем меньше в ней ломается при обновлении CLI.
 */

/** Итог прогона: приходит последним и несёт расход. */
export interface Done {
  kind: "done";
  ok: boolean;
  text: string;
  conversationId?: string;
  report: Record<string, unknown>;
}

export type Step =
  | { kind: "started"; conversationId?: string; tools: number; servers: string[]; model?: string }
  | { kind: "said"; text: string }
  | { kind: "using"; tool: string; input?: Record<string, unknown> }
  | Done;

function textOf(content: unknown): string {
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const block of content) {
    if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
      const text = (block as { text?: unknown }).text;
      if (typeof text === "string") parts.push(text);
    }
  }
  return parts.join("").trim();
}

/**
 * Чем именно агент воспользовался и с чем.
 *
 * Аргументы нужны потребителю снаружи: по ним видно, ЧТО изменилось, и что стоит перезапросить.
 * Спрашивать об этом самого агента значило бы завести второй источник правды, который однажды
 * разойдётся с первым.
 *
 * Крупные значения сюда не едут — см. `slim`.
 */
function toolsOf(content: unknown): { tool: string; input?: Record<string, unknown> }[] {
  if (!Array.isArray(content)) return [];
  const used: { tool: string; input?: Record<string, unknown> }[] = [];
  for (const block of content) {
    if (block && typeof block === "object" && (block as { type?: string }).type === "tool_use") {
      const name = (block as { name?: unknown }).name;
      if (typeof name !== "string") continue;
      const input = (block as { input?: unknown }).input;
      used.push({ tool: name, input: slim(input) });
    }
  }
  return used;
}

/**
 * Оставить от аргументов только опознавательное.
 *
 * Скаляры целиком: по ним снаружи узнаю́т, какая запись тронута. Объекты, списки и длинные
 * строки заменяются пометкой — это тело, которое всё равно перезапрашивают у источника, а гнать
 * его обратно значит платить за один и тот же груз дважды.
 */
function slim(input: unknown): Record<string, unknown> | undefined {
  if (!input || typeof input !== "object" || Array.isArray(input)) return undefined;

  const kept: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input as Record<string, unknown>)) {
    if (value === null || typeof value === "number" || typeof value === "boolean") {
      kept[key] = value;
    } else if (typeof value === "string") {
      kept[key] = value.length <= 200 ? value : `«${value.length} знаков»`;
    } else {
      kept[key] = Array.isArray(value) ? `«список из ${value.length}»` : "«объект»";
    }
  }
  return kept;
}

/**
 * Перевести одно событие CLI в наши шаги.
 *
 * Незнакомое событие даёт пустой список, а не отказ: CLI вправе добавлять свои типы, и падать
 * от каждого нового было бы хрупкостью на ровном месте. Терять при этом нечего — всё, что
 * важно, приходит ещё и в итоговом отчёте.
 */
export function stepsOf(event: Record<string, unknown>): Step[] {
  const type = event["type"];

  if (type === "system" && event["subtype"] === "init") {
    const servers = Array.isArray(event["mcp_servers"])
      ? (event["mcp_servers"] as { name?: unknown }[])
          .map((s) => (typeof s?.name === "string" ? s.name : ""))
          .filter(Boolean)
      : [];
    return [
      {
        kind: "started",
        conversationId: typeof event["session_id"] === "string" ? event["session_id"] : undefined,
        tools: Array.isArray(event["tools"]) ? event["tools"].length : 0,
        servers,
        model: typeof event["model"] === "string" ? event["model"] : undefined,
      },
    ];
  }

  if (type === "assistant") {
    const content = (event["message"] as { content?: unknown } | undefined)?.content;
    const steps: Step[] = [];
    const said = textOf(content);
    if (said) steps.push({ kind: "said", text: said });
    for (const used of toolsOf(content)) steps.push({ kind: "using", ...used });
    return steps;
  }

  if (type === "result") {
    const report = event as Record<string, unknown>;
    return [
      {
        kind: "done",
        ok: report["is_error"] !== true,
        text: typeof report["result"] === "string" ? report["result"].trim() : "",
        conversationId:
          typeof report["session_id"] === "string" ? report["session_id"] : undefined,
        report,
      },
    ];
  }

  return [];
}

/** Разрезать поток байтов на строки-объекты, не теряя хвоста между кусками. */
export function lines(): (chunk: string) => Record<string, unknown>[] {
  let rest = "";

  return (chunk: string) => {
    // Кусок приходит как попало и рвётся посреди строки: без накопления хвоста каждая вторая
    // строка разбиралась бы как испорченная.
    const whole = rest + chunk;
    const parts = whole.split("\n");
    rest = parts.pop() ?? "";

    const events: Record<string, unknown>[] = [];
    for (const part of parts) {
      const line = part.trim();
      if (!line) continue;
      try {
        events.push(JSON.parse(line) as Record<string, unknown>);
      } catch {
        // Строка не разобралась — пропускаем её, но не поток: одна испорченная строка не
        // повод терять всё остальное, а важное придёт ещё и в итоговом отчёте.
      }
    }
    return events;
  };
}
