/**
 * Разговор с сервисом. Единственное место в пульте, которое знает про HTTP.
 *
 * Пульт не получает возможностей мимо API: всё, что он умеет, умеет и сервис. Иначе появится
 * второй способ делать одно и то же, и они разойдутся.
 */

const BASE = "/api";

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

export interface Refusal {
  name: string;
  means: string;
  where?: string | null;
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
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
  agents: () => call<{ agent: string; ok: boolean; card?: { name: string } | null }[]>("/agents"),
  probeAgents: () =>
    call<{ agent: string; ok: boolean }[]>("/agents/probe", { method: "POST" }),

  sessions: () => call<Session[]>("/sessions"),
  createSession: (body: { recipe: string; passport: string; agent: string; title?: string }) =>
    call<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  messages: (id: string) => call<Message[]>(`/sessions/${id}/messages`),
  runs: (id: string) => call<Run[]>(`/sessions/${id}/runs`),
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

/**
 * Слушать ход прогонов сессии.
 *
 * Возвращает функцию отписки: без неё поток пережил бы уход со страницы, и каждый переход
 * оставлял бы после себя открытое соединение.
 */
export function watch(id: string, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`${BASE}/sessions/${id}/events`);

  const handle = (raw: MessageEvent<string>): void => {
    try {
      onEvent(JSON.parse(raw.data) as RunEvent);
    } catch {
      // Испорченное событие пропускаем: терять из-за него весь поток незачем, состояние
      // всегда можно дочитать из истории.
    }
  };

  for (const name of ["run-started", "run-step", "run-finished", "run-canceled"]) {
    source.addEventListener(name, handle as EventListener);
  }

  return () => source.close();
}
