/**
 * A2A-агент поверх локального Claude Code.
 *
 * Снаружи — общий протокол, внутри — конкретный инструмент. Оркестратор не знает, что здесь
 * CLI: он знает адрес и визитку. Появится второй рантайм — встанет рядом таким же агентом,
 * и менять оркестратор не придётся.
 */

import express from "express";
import { A2A_PROTOCOL_VERSION, AGENT_CARD_PATH, type AgentCard } from "@a2a-js/sdk";
import { DefaultRequestHandler, InMemoryTaskStore } from "@a2a-js/sdk/server";
import { agentCardHandler, jsonRpcHandler, UserBuilder } from "@a2a-js/sdk/server/express";

import { ClaudeExecutor } from "./executor.js";

const PORT = Number(process.env.PORT ?? 9100);

// Адрес, по которому агента видят СНАРУЖИ. Внутри сети докера это имя сервиса, а не localhost:
// визитку читает оркестратор из соседнего контейнера, и localhost для него — он сам.
const PUBLIC_URL = process.env.AGENT_PUBLIC_URL ?? `http://claude:${PORT}/`;

const card: AgentCard = {
  name: "Claude Code",
  description:
    "Локальный Claude Code как агент: получает инструкцию и набор MCP-серверов, выполняет задачу.",
  supportedInterfaces: [
    {
      url: PUBLIC_URL,
      protocolBinding: "JSONRPC",
      tenant: "",
      protocolVersion: A2A_PROTOCOL_VERSION,
    },
  ],
  provider: { organization: "NeuroBox", url: "https://github.com/egor6-66/NeuroBox" },
  version: "0.1.0",
  capabilities: {
    streaming: true,
    pushNotifications: false,
    extensions: [],
    extendedAgentCard: false,
  },
  securitySchemes: {},
  securityRequirements: [],
  defaultInputModes: ["text"],
  defaultOutputModes: ["text"],
  skills: [
    {
      id: "run-recipe",
      name: "Выполнить задачу по рецепту",
      description:
        "Принимает задачу текстом; инструкция и MCP-серверы приходят метаданными развёртки.",
      tags: ["claude-code", "mcp"],
      examples: ["Разбери, что делает этот пакет", "Обнови доку по коду"],
      inputModes: ["text"],
      outputModes: ["text"],
      securityRequirements: [],
    },
  ],
  documentationUrl: "",
  signatures: [],
};

const requestHandler = new DefaultRequestHandler(card, new InMemoryTaskStore(), new ClaudeExecutor());

const app = express();
app.use(`/${AGENT_CARD_PATH}`, agentCardHandler({ agentCardProvider: requestHandler }));
app.use(jsonRpcHandler({ requestHandler, userBuilder: UserBuilder.noAuthentication }));

app.listen(PORT, () => {
  console.log(`[claude-agent] слушает :${PORT}, визитка на /${AGENT_CARD_PATH}`);
});
