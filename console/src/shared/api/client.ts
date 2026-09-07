/**
 * Разговор с сервисом. Единственное место в пульте, которое знает про HTTP.
 *
 * Пульт не получает возможностей мимо API: всё, что он умеет, умеет и сервис. Иначе появится
 * второй способ делать одно и то же, и они разойдутся.
 */

const BASE = "/api";
const KEEP = "neurobox_token";

/** Запасное место на случай закрытого хранилища. Смотри `token`. */
let remembered = "";

/**
 * Токен доступа.
 *
 * Хранится в локальном хранилище, а НЕ кукой, и причина в соседстве. На машине рядом живёт другой
 * продукт на другом порту того же адреса. Браузер различает места по схеме, имени и порту — но
 * куки по портам НЕ разделяет вовсе: кука, поставленная пультом, уезжала бы соседу с каждым
 * запросом к нему. Локальное хранилище привязано к источнику целиком, вместе с портом, и соседу
 * недоступно.
 *
 * Плата за это — поток событий: браузерный источник событий заголовков задавать не умеет, поэтому
 * поток читается обычным запросом. Разбор — у `watch`.
 *
 * Когда появится общий модуль авторизации, здесь окажется его сессия, а форма обращения не
 * изменится.
 */
export const token = {
  get: (): string => {
    try {
      return localStorage.getItem(KEEP) ?? "";
    } catch {
      // Хранилище бывает закрыто настройками браузера. Тогда токен живёт до перезагрузки
      // страницы — это хуже, но работает, в отличие от падения на первом же обращении.
      return remembered;
    }
  },
  set: (value: string): void => {
    remembered = value;
    try {
      if (value) localStorage.setItem(KEEP, value);
      else localStorage.removeItem(KEEP);
    } catch {
      // См. выше: остаётся память страницы.
    }
  },
};

export interface Passport {
  name: string;
  provider: string;
  model: string;
  description?: string | null;
  context?: number | null;
  layer: string;
}

export interface Recipe {
  name: string;
  description?: string | null;
  seeds: string[];
  layer: string;
}

export interface Seed {
  name: string;
  kind: "server" | "knowledge";
  description?: string | null;
  layer: string;
}

export interface Agent {
  name: string;
  url: string;
  description?: string | null;
  layer: string;
}

export interface Tool {
  name: string;
  description?: string | null;
  input_schema: JsonSchema;
}

/** Кусок схемы входа — ровно то, что нужно, чтобы построить поле формы. */
export interface JsonSchema {
  type?: string | string[];
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: (string | number)[];
  items?: JsonSchema;
  default?: unknown;
}

/** Последнее, что агент о себе сказал. Зеркало `Server`, только уровнем выше. */
export interface KnownAgent {
  agent: string;
  ok: boolean;
  card?: { name: string } | null;
}

export interface Server {
  seed: string;
  ok: boolean;
  tools: Tool[];
  instructions?: string | null;
  weight_chars: number;
  refusals: Refusal[];
}

export interface Called {
  ok: boolean;
  content: { type?: string; text?: string }[];
  structured?: Record<string, unknown> | null;
  refusals: Refusal[];
}

export interface Refusal {
  name: string;
  means: string;
  where?: string | null;
}

export interface Note {
  kind: string;
  what: string;
  where?: string | null;
  workaround?: string | null;
  created_at: string;
}

export interface Session {
  id: string;
  title: string | null;
  recipe: string;
  passport: string;
  agent: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  author: "human" | "agent";
  text: string;
  run_id: string | null;
  created_at: string;
}

export interface Run {
  id: string;
  state: "working" | "completed" | "failed" | "canceled";
  refusal?: string | null;
  means?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  cache_creation_tokens?: number | null;
  cache_read_tokens?: number | null;
  cost_micros?: number | null;
  duration_ms?: number | null;
  created_at: string;
  finished_at?: string | null;
}

/** Отказ сервиса, донесённый как есть. */
export class ServiceError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const carried = token.get();
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(carried ? { Authorization: `Bearer ${carried}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    // Причина берётся из ответа сервиса: он объясняет отказы словами, и пересказывать их
    // своими значило бы потерять то, ради чего они так написаны.
    let means = `сервис ответил ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") means = body.detail;
    } catch {
      // Тело не разобралось — остаётся код ответа, он лучше молчания.
    }
    throw new ServiceError(response.status, means);
  }

  return (await response.json()) as T;
}

export const api = {
  passports: () => call<Passport[]>("/catalog/passports"),
  recipes: () => call<Recipe[]>("/catalog/recipes"),
  seeds: () => call<Seed[]>("/catalog/seeds"),
  refusals: () => call<Refusal[]>("/catalog/refusals"),
  agents: () => call<KnownAgent[]>("/agents"),
  probeAgents: () => call<KnownAgent[]>("/agents/probe", { method: "POST" }),

  servers: () => call<Server[]>("/mcp/servers"),
  probeServers: () => call<Server[]>("/mcp/probe", { method: "POST" }),
  callTool: (seed: string, tool: string, args: Record<string, unknown>) =>
    call<Called>(`/mcp/servers/${encodeURIComponent(seed)}/tools/${encodeURIComponent(tool)}`, {
      method: "POST",
      body: JSON.stringify({ arguments: args }),
    }),

  sessions: () => call<Session[]>("/sessions"),
  createSession: (body: { recipe: string; passport: string; agent: string; title?: string }) =>
    call<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  messages: (id: string) => call<Message[]>(`/sessions/${id}/messages`),
  runs: (id: string) => call<Run[]>(`/sessions/${id}/runs`),
  notes: (id: string) => call<Note[]>(`/sessions/${id}/notes`),
  say: (id: string, text: string) =>
    call<{ run: Run }>(`/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  cancel: (id: string, run: string) =>
    call<Run>(`/sessions/${id}/runs/${run}/cancel`, { method: "POST" }),
};

export interface RunEvent {
  event: "run-started" | "run-step" | "run-finished" | "run-canceled";
  run: string;
  kind?: string;
  text?: string;
  reply?: string;
  state?: string;
  refusal?: string | null;
  means?: string | null;
}

/** Разобрать один кадр потока и донести событие. */
function deliver(frame: string, onEvent: (event: RunEvent) => void): void {
  // Кадр — несколько строк вида `имя: значение`. Нужны только `data`; строка, начинающаяся с
  // двоеточия, это отбивка, которой сервис держит соединение живым.
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trim())
    .join("\n");

  if (!data) return;

  try {
    onEvent(JSON.parse(data) as RunEvent);
  } catch {
    // Испорченное событие пропускаем: терять из-за него весь поток незачем, состояние всегда
    // можно дочитать из истории.
  }
}

/**
 * Слушать ход прогонов сессии.
 *
 * Читается обычным запросом, а не источником событий браузера. Причина: источнику нельзя задать
 * заголовок, а токен ездит именно заголовком — кукой его класть нельзя, куки не разделяются по
 * портам и утекли бы соседу (разбор у `token`). Класть токен в адрес нельзя тем более: он осел бы
 * в логах посредника и в истории браузера.
 *
 * Возвращает функцию отписки: без неё поток пережил бы уход со страницы, и каждый переход
 * оставлял бы после себя открытое соединение.
 */
export function watch(id: string, onEvent: (event: RunEvent) => void): () => void {
  const stop = new AbortController();

  const listen = async (): Promise<void> => {
    const carried = token.get();
    const response = await fetch(`${BASE}/sessions/${id}/events`, {
      headers: {
        Accept: "text/event-stream",
        ...(carried ? { Authorization: `Bearer ${carried}` } : {}),
      },
      signal: stop.signal,
    });

    if (!response.ok || !response.body) {
      throw new ServiceError(response.status, `поток не открылся: ${response.status}`);
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let rest = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;

      // Переводы строк приводятся к одному виду: сервис разделяет строки по-своему, и разбор,
      // знающий только один вариант, молча не увидел бы ни одного события.
      rest += value.replace(/\r\n/g, "\n");

      let edge = rest.indexOf("\n\n");
      while (edge !== -1) {
        deliver(rest.slice(0, edge), onEvent);
        rest = rest.slice(edge + 2);
        edge = rest.indexOf("\n\n");
      }
    }
  };

  // Соединение рвётся: сон машины, перезапуск сервиса, посредник. Источник событий возвращался
  // сам, обычный запрос — нет, поэтому возвращаемся здесь. Пауза растёт, чтобы упавший сервис не
  // получал шквал попыток.
  void (async () => {
    let pause = 1000;
    while (!stop.signal.aborted) {
      try {
        await listen();
        pause = 1000;
      } catch {
        if (stop.signal.aborted) return;
      }
      await new Promise<void>((wake) => {
        setTimeout(wake, pause);
      });
      pause = Math.min(pause * 2, 15000);
    }
  })();

  return () => stop.abort();
}
