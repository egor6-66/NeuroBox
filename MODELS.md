# 🧮 Модели с вызовом инструментов: цена и уровень

Снято из открытого API OpenRouter **03.10.2026**. Цены меняются месяцами —
перед решением сверяйтесь с источником, а не с этим файлом.

Отбор один и жёсткий: **модель умеет вызывать инструменты**. Без этого MCP-зоны не работают, и
для бокса такая модель бесполезна, какой бы дешёвой ни была. Из 466 моделей каталога таких
398; 3 из них — маршрутизаторы без своей цены, они здесь не считаются.

> [!IMPORTANT]
> Дешёвая модель по API — **не замена Claude Code**, а другой род рантайма. Claude Code сам и
> есть агент: держит переписку, крутит цикл вызова инструментов, решает, когда остановиться.
> Сырая модель за API ничего из этого не делает — цикл пишем мы. Это пункт `two-kinds-of-runtime`
> в `ROADMAP.yaml`, и он ещё не сделан.

## Как читать

Цены — **доллары за миллион токенов**, вход и выход отдельно. Уровень считается по сумме
«миллион туда плюс миллион обратно»: так разные перекосы вендоров сравниваются одной меркой.

| Уровень | Сумма за 1M+1M |
|---|---|
| 🟢 бесплатно | 0 |
| 🔵 центы | до $0.50 |
| 🟡 дешёвый | $0.50 – $3 |
| 🟠 средний | $3 – $15 |
| 🔴 дорогой | свыше $15 |

Столбец «ум» помечает отдельный режим размышления (`reasoning`): модель думает токенами, и выход
у неё дороже. Признак слабо различающий — он есть у 79% моделей с инструментами, поэтому в списке
бесплатных его нет вовсе: там он стоит у всех.

## 🟢 Бесплатные (19)

Через OpenRouter у вариантов с `:free` предел — **20 запросов в минуту и 50 в сутки**; после
единоразовой покупки на $10 суточный предел становится 1000. У Google свой бесплатный уровень
напрямую, но там плата данными: запросы идут на улучшение их продуктов. Для демо годится, для
чужих данных — нет.

| Модель | Контекст |
|---|---|
| `apodex/apodex-1.1-mini:free` | 262k |
| `cohere/north-mini-code:free` | 256k |
| `dots-studio/dots-3-note-preview:free` | 512k |
| `google/gemma-4-26b-a4b-it:free` | 262k |
| `google/gemma-4-31b-it:free` | 262k |
| `inclusionai/ling-3.0-flash-sante:free` | 262k |
| `inclusionai/ling-3.1-flash` | 262k |
| `liquid/lfm-2.5-2.6b:free` | 65k |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 256k |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262k |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1M |
| `nvidia/nemotron-3.5-lightning:free` | 1M |
| `openrouter/free` | 200k |
| `poolside/laguna-s-2.1:free` | 262k |
| `poolside/laguna-xs-2.1:free` | 262k |
| `qwen/qwen3.8-27b:free` | 262k |
| `stealth/space-bunny-alpha` | 1M |
| `thinkingmachines/inkling-small:free` | 1M |
| `thinkingmachines/inkling:free` | 1M |

## 🔵🟡 Платные до $3 за 1M+1M (196)

Весь дешёвый край — китайские семейства: DeepSeek, Qwen, GLM (Zhipu), Ling, ByteDance, StepFun,
MiniMax, Moonshot. Рядом с ними держатся открытые модели Mistral, Google Gemma и OpenAI `gpt-oss`.

| Уровень | Модель | Вход | Выход | Контекст | Ум |
|---|---|---|---|---|---|
| 🔵 центы | `mistralai/mistral-nemo` | 0.019 | 0.03 | 131k | — |
| 🔵 центы | `inclusionai/ling-3.0-flash-vl` | 0.021 | 0.062 | 262k | да |
| 🔵 центы | `inclusionai/ling-3.0-flash` | 0.021 | 0.063 | 262k | да |
| 🔵 центы | `deepseek/deepseek-v4-flash` | 0.028 | 0.056 | 1M | да |
| 🔵 центы | `openai/gpt-oss-20b` | 0.018 | 0.09 | 131k | да |
| 🔵 центы | `meta-llama/llama-3.1-8b-instruct` | 0.05 | 0.08 | 131k | — |
| 🔵 центы | `openai/gpt-oss-20b:batch` | 0.024 | 0.112 | 131k | да |
| 🔵 центы | `mistralai/ministral-8b-2512:batch` | 0.075 | 0.075 | 262k | — |
| 🔵 центы | `qwen/qwen3.7-flash` | 0.03 | 0.13 | 1M | да |
| 🔵 центы | `inclusionai/ling-3.0-flash-fin` | 0.042 | 0.123 | 262k | да |
| 🔵 центы | `openai/gpt-oss-120b:batch` | 0.03 | 0.136 | 131k | да |
| 🔵 центы | `amazon/nova-micro-v1` | 0.035 | 0.14 | 128k | — |
| 🔵 центы | `poolside/laguna-xs-2.1` | 0.06 | 0.12 | 262k | да |
| 🔵 центы | `inception/mercury-2.5` | 0.04 | 0.15 | 260k | да |
| 🔵 центы | `google/gemma-3-12b-it` | 0.05 | 0.15 | 131k | — |
| 🔵 центы | `mistralai/ministral-3b-2512` | 0.1 | 0.1 | 131k | — |
| 🔵 центы | `rekaai/reka-edge` | 0.1 | 0.1 | 16k | — |
| 🔵 центы | `openai/gpt-oss-120b` | 0.037 | 0.17 | 131k | да |
| 🔵 центы | `openai/gpt-5-nano:batch` | 0.025 | 0.2 | 400k | да |
| 🔵 центы | `nvidia/nemotron-3.5-lightning` | 0.059 | 0.17 | 262k | да |
| 🔵 центы | `qwen/qwen3-30b-a3b-instruct-2507` | 0.048 | 0.193 | 262k | — |
| 🔵 центы | `google/gemini-2.5-flash-lite:batch` | 0.05 | 0.2 | 1M | да |
| 🔵 центы | `nvidia/nemotron-3-nano-30b-a3b` | 0.05 | 0.2 | 262k | да |
| 🔵 центы | `openai/gpt-4.1-nano:batch` | 0.05 | 0.2 | 1M | — |
| 🔵 центы | `upstage/solar-mini4` | 0.05 | 0.2 | 524k | да |
| 🔵 центы | `qwen/qwen3.5-9b` | 0.1 | 0.15 | 262k | да |
| 🔵 центы | `z-ai/glm-5.3-flash:batch` | 0.06 | 0.2 | 1M | да |
| 🔵 центы | `poolside/laguna-s-2.1` | 0.09 | 0.18 | 1M | да |
| 🔵 центы | `google/gemma-4-26b-a4b-it` | 0.068 | 0.225 | 262k | да |
| 🔵 центы | `amazon/nova-lite-v1` | 0.06 | 0.24 | 300k | — |
| 🔵 центы | `meta/muse-spark-1.2-contributor` | 0.1 | 0.2 | 1M | да |
| 🔵 центы | `meta/muse-spark-1.3-contributor` | 0.1 | 0.2 | 1M | да |
| 🔵 центы | `mistralai/ministral-8b-2512` | 0.15 | 0.15 | 262k | — |
| 🔵 центы | `openai/gpt-6-luna-pro:batch` | 0.05 | 0.25 | 1M | да |
| 🔵 центы | `openai/gpt-6-luna:batch` | 0.05 | 0.25 | 1M | да |
| 🔵 центы | `qwen/qwen-2.5-7b-instruct` | 0.1 | 0.2 | 32k | — |
| 🔵 центы | `ibm-granite/granite-4.2-8b` | 0.06 | 0.25 | 131k | да |
| 🔵 центы | `nex-agi/nex-n2.5-pro` | 0.075 | 0.25 | 262k | да |
| 🔵 центы | `qwen/qwen3.5-flash-02-23` | 0.065 | 0.26 | 1M | да |
| 🔵 центы | `mistralai/mistral-small-3.2-24b-instruct` | 0.094 | 0.25 | 256k | — |
| 🔵 центы | `qwen/qwen3-coder-30b-a3b-instruct` | 0.07 | 0.28 | 262k | — |
| 🔵 центы | `qwen/qwen3-14b` | 0.12 | 0.24 | 131k | да |
| 🔵 центы | `qwen/qwen3-32b` | 0.08 | 0.28 | 131k | да |
| 🔵 центы | `bytedance-seed/seed-1.6-flash` | 0.075 | 0.3 | 262k | да |
| 🔵 центы | `mistralai/mistral-small-2603:batch` | 0.075 | 0.3 | 262k | да |
| 🔵 центы | `openai/gpt-4o-mini:batch` | 0.075 | 0.3 | 128k | — |
| 🔵 центы | `openai/gpt-oss-safeguard-20b` | 0.075 | 0.3 | 131k | да |
| 🔵 центы | `meta-llama/llama-4-scout` | 0.1 | 0.3 | 1M | — |
| 🔵 центы | `mistralai/ministral-14b-2512` | 0.2 | 0.2 | 262k | — |
| 🔵 центы | `mistralai/voxtral-small-24b-2507` | 0.1 | 0.3 | 32k | — |
| 🔵 центы | `stepfun/step-3.5-flash` | 0.1 | 0.3 | 262k | да |
| 🔵 центы | `meta-llama/llama-3.3-70b-instruct` | 0.1 | 0.32 | 131k | — |
| 🔵 центы | `xiaomi/mimo-v2.5` | 0.14 | 0.28 | 1M | да |
| 🔵 центы | `xiaomi/mimo-v2.6-flash` | 0.14 | 0.28 | 1M | да |
| 🔵 центы | `google/gemma-4-31b-it` | 0.09 | 0.34 | 262k | да |
| 🔵 центы | `qwen/qwen3-235b-a22b-2507` | 0.087 | 0.35 | 262k | — |
| 🔵 центы | `deepseek/deepseek-v4.1-flash:batch` | 0.112 | 0.336 | 1M | да |
| 🔵 центы | `openai/gpt-5-nano` | 0.05 | 0.4 | 400k | да |
| 🔵 центы | `upstage/solar-pro4` | 0.09 | 0.36 | 524k | да |
| 🔵 центы | `z-ai/glm-4.7-flash` | 0.061 | 0.4 | 200k | да |
| 🔵 центы | `bytedance-seed/seed-2.0-mini` | 0.1 | 0.4 | 262k | да |
| 🔵 центы | `google/gemini-2.5-flash-lite` | 0.1 | 0.4 | 1M | да |
| 🔵 центы | `openai/gpt-4.1-nano` | 0.1 | 0.4 | 1M | — |
| 🟡 дешёвый | `qwen/qwen3-vl-32b-instruct` | 0.104 | 0.416 | 131k | — |
| 🟡 дешёвый | `google/gemma-3-27b-it` | 0.08 | 0.45 | 131k | — |
| 🟡 дешёвый | `nvidia/nemotron-3-super-120b-a12b` | 0.08 | 0.45 | 262k | да |
| 🟡 дешёвый | `~z-ai/glm-flash-latest` | 0.035 | 0.5 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-8b` | 0.117 | 0.455 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3-vl-8b-instruct` | 0.117 | 0.455 | 262k | — |
| 🟡 дешёвый | `prism-ml/ternary-bonsai-2-27b` | 0.075 | 0.5 | 262k | да |
| 🟡 дешёвый | `mistralai/codestral-2508:batch` | 0.15 | 0.45 | 256k | — |
| 🟡 дешёвый | `openai/gpt-6-luna` | 0.1 | 0.5 | 1M | да |
| 🟡 дешёвый | `openai/gpt-6-luna-pro` | 0.1 | 0.5 | 1M | да |
| 🟡 дешёвый | `~openai/gpt-luna-latest` | 0.1 | 0.5 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-30b-a3b` | 0.12 | 0.5 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3.8-flash` | 0.15 | 0.47 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3.8-omni-flash` | 0.15 | 0.47 | 1M | да |
| 🟡 дешёвый | `~deepseek/deepseek-flash-latest` | 0.02 | 0.6 | 1M | да |
| 🟡 дешёвый | `deepseek/deepseek-v4-pro` | 0.209 | 0.418 | 1M | да |
| 🟡 дешёвый | `z-ai/glm-5.3-flash` | 0.15 | 0.5 | 1M | да |
| 🟡 дешёвый | `tencent/hy3` | 0.132 | 0.528 | 262k | да |
| 🟡 дешёвый | `deepseek/deepseek-v3.2-exp` | 0.27 | 0.41 | 163k | да |
| 🟡 дешёвый | `deepseek/deepseek-v3.2` | 0.28 | 0.42 | 163k | да |
| 🟡 дешёвый | `openai/gpt-5.6-luna-pro:batch` | 0.1 | 0.6 | 1M | да |
| 🟡 дешёвый | `openai/gpt-5.6-luna:batch` | 0.1 | 0.6 | 1M | да |
| 🟡 дешёвый | `openai/gpt-5.4-nano:batch` | 0.1 | 0.625 | 400k | да |
| 🟡 дешёвый | `cohere/command-r-08-2024` | 0.15 | 0.6 | 128k | — |
| 🟡 дешёвый | `mistralai/mistral-small-2603` | 0.15 | 0.6 | 262k | да |
| 🟡 дешёвый | `openai/gpt-4o-mini` | 0.15 | 0.6 | 128k | — |
| 🟡 дешёвый | `openai/gpt-4o-mini-2024-07-18` | 0.15 | 0.6 | 128k | — |
| 🟡 дешёвый | `qwen/qwen3-vl-30b-a3b-instruct` | 0.15 | 0.6 | 262k | — |
| 🟡 дешёвый | `upstage/solar-pro-3` | 0.15 | 0.6 | 131k | да |
| 🟡 дешёвый | `qwen/qwen-2.5-72b-instruct` | 0.36 | 0.4 | 32k | — |
| 🟡 дешёвый | `tencent/hy3-preview` | 0.18 | 0.6 | 262k | да |
| 🟡 дешёвый | `meta-llama/llama-3.1-70b-instruct` | 0.4 | 0.4 | 131k | — |
| 🟡 дешёвый | `mistralai/mistral-saba` | 0.2 | 0.6 | 32k | — |
| 🟡 дешёвый | `meta-llama/llama-4-maverick` | 0.188 | 0.652 | 1M | — |
| 🟡 дешёвый | `deepseek/deepseek-v4-flash-vision-exp` | 0.216 | 0.647 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.1-flash-lite:batch` | 0.125 | 0.75 | 1M | да |
| 🟡 дешёвый | `mistralai/mistral-small-3.1-24b-instruct` | 0.351 | 0.555 | 128k | — |
| 🟡 дешёвый | `qwen/qwen3-coder-next` | 0.12 | 0.8 | 262k | — |
| 🟡 дешёвый | `z-ai/glm-4.5-air` | 0.13 | 0.85 | 131k | да |
| 🟡 дешёвый | `openai/gpt-4.1-mini:batch` | 0.2 | 0.8 | 1M | — |
| 🟡 дешёвый | `inception/mercury-2` | 0.25 | 0.75 | 128k | да |
| 🟡 дешёвый | `mistralai/mistral-large-2512:batch` | 0.25 | 0.75 | 262k | — |
| 🟡 дешёвый | `openai/gpt-3.5-turbo:batch` | 0.25 | 0.75 | 16k | — |
| 🟡 дешёвый | `qwen/qwen-plus` | 0.26 | 0.78 | 1M | — |
| 🟡 дешёвый | `qwen/qwen-plus-2025-07-28` | 0.26 | 0.78 | 1M | — |
| 🟡 дешёвый | `arcee-ai/trinity-large-thinking` | 0.25 | 0.8 | 262k | да |
| 🟡 дешёвый | `minimax/minimax-m2.7` | 0.21 | 0.84 | 204k | да |
| 🟡 дешёвый | `openai/gpt-5-mini:batch` | 0.125 | 1 | 400k | да |
| 🟡 дешёвый | `qwen/qwen3.5-35b-a3b` | 0.15 | 1 | 262k | да |
| 🟡 дешёвый | `qwen/qwen3.6-35b-a3b` | 0.15 | 1 | 262k | да |
| 🟡 дешёвый | `qwen/qwen3-coder-flash` | 0.195 | 0.975 | 1M | — |
| 🟡 дешёвый | `deepseek/deepseek-chat-v3.1` | 0.25 | 0.95 | 163k | да |
| 🟡 дешёвый | `mistralai/codestral-2508` | 0.3 | 0.9 | 256k | — |
| 🟡 дешёвый | `mistralai/mistral-medium-3.1:batch` | 0.2 | 1 | 131k | — |
| 🟡 дешёвый | `z-ai/glm-4.6v` | 0.3 | 0.9 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3-next-80b-a3b-instruct` | 0.1 | 1.1 | 262k | — |
| 🟡 дешёвый | `deepseek/deepseek-v3.1-terminus` | 0.27 | 1 | 163k | да |
| 🟡 дешёвый | `deepseek/deepseek-chat` | 0.257 | 1.029 | 163k | — |
| 🟡 дешёвый | `deepseek/deepseek-v4-flash-0731` | 0.019 | 1.28 | 1M | да |
| 🟡 дешёвый | `~deepseek/deepseek-v4-flash-latest` | 0.019 | 1.28 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-coder` | 0.3 | 1 | 262k | — |
| 🟡 дешёвый | `xiaomi/mimo-v2.5-pro` | 0.435 | 0.87 | 1M | да |
| 🟡 дешёвый | `xiaomi/mimo-v2.6-pro` | 0.435 | 0.87 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3.6-flash` | 0.188 | 1.125 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-next-80b-a3b-thinking` | 0.15 | 1.2 | 262k | да |
| 🟡 дешёвый | `stepfun/step-3.7-flash` | 0.2 | 1.15 | 262k | да |
| 🟡 дешёвый | `minimax/minimax-m2.5` | 0.27 | 1.08 | 204k | да |
| 🟡 дешёвый | `google/gemini-2.5-flash:batch` | 0.15 | 1.25 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.5-flash-lite:batch` | 0.15 | 1.25 | 1M | да |
| 🟡 дешёвый | `openai/gpt-5.6-luna` | 0.2 | 1.2 | 1M | да |
| 🟡 дешёвый | `openai/gpt-5.6-luna-pro` | 0.2 | 1.2 | 1M | да |
| 🟡 дешёвый | `deepseek/deepseek-chat-v3-0324` | 0.29 | 1.14 | 163k | — |
| 🟡 дешёвый | `openai/gpt-5.4-nano` | 0.2 | 1.25 | 400k | да |
| 🟡 дешёвый | `deepseek/deepseek-v4.1-flash` | 0.3 | 1.2 | 1M | да |
| 🟡 дешёвый | `meituan/longcat-2.0` | 0.3 | 1.2 | 1M | да |
| 🟡 дешёвый | `minimax/minimax-m2` | 0.3 | 1.2 | 204k | да |
| 🟡 дешёвый | `minimax/minimax-m2.1` | 0.3 | 1.2 | 204k | да |
| 🟡 дешёвый | `minimax/minimax-m3` | 0.3 | 1.2 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3.7-plus` | 0.32 | 1.28 | 1M | да |
| 🟡 дешёвый | `z-ai/glm-5.3-flashx` | 0.37 | 1.25 | 1M | да |
| 🟡 дешёвый | `perceptron/perceptron-mk1.5` | 0.15 | 1.5 | 36k | да |
| 🟡 дешёвый | `thinkingmachines/inkling-small` | 0.45 | 1.2 | 524k | да |
| 🟡 дешёвый | `sao10k/l3.1-euryale-70b` | 0.85 | 0.85 | 131k | — |
| 🟡 дешёвый | `google/gemini-3-flash-preview:batch` | 0.25 | 1.5 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.1-flash-lite` | 0.25 | 1.5 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.1-flash-lite-preview` | 0.25 | 1.5 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3.5-27b` | 0.195 | 1.56 | 262k | да |
| 🟡 дешёвый | `cohere/command-a-plus` | 0.3 | 1.5 | 192k | да |
| 🟡 дешёвый | `qwen/qwen3.5-plus-02-15` | 0.26 | 1.56 | 1M | да |
| 🟡 дешёвый | `meta/muse-glimmer-30b` | 0.35 | 1.5 | 131k | да |
| 🟡 дешёвый | `openai/gpt-4.1-mini` | 0.4 | 1.6 | 1M | — |
| 🟡 дешёвый | `mistralai/mistral-large-2512` | 0.5 | 1.5 | 262k | — |
| 🟡 дешёвый | `openai/gpt-3.5-turbo` | 0.5 | 1.5 | 16k | — |
| 🟡 дешёвый | `aion-labs/aion-3.0-mini` | 0.7 | 1.4 | 131k | да |
| 🟡 дешёвый | `aion-labs/aion-3.5-mini` | 0.7 | 1.4 | 262k | да |
| 🟡 дешёвый | `qwen/qwen3.5-plus-20260420` | 0.3 | 1.8 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-vl-235b-a22b-instruct` | 0.21 | 1.9 | 262k | — |
| 🟡 дешёвый | `z-ai/glm-4.6` | 0.43 | 1.75 | 204k | да |
| 🟡 дешёвый | `bytedance-seed/seed-1.6` | 0.25 | 2 | 262k | да |
| 🟡 дешёвый | `bytedance-seed/seed-2.0-lite` | 0.25 | 2 | 262k | да |
| 🟡 дешёвый | `google/gemini-3.6-flash:batch` | 0.375 | 1.875 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.7-flash:batch` | 0.375 | 1.875 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.8-flash:batch` | 0.375 | 1.875 | 1M | да |
| 🟡 дешёвый | `openai/gpt-5-mini` | 0.25 | 2 | 400k | да |
| 🟡 дешёвый | `openai/gpt-5.1-codex-mini` | 0.25 | 2 | 400k | да |
| 🟡 дешёвый | `qwen/qwen3-235b-a22b` | 0.455 | 1.82 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3.6-plus` | 0.325 | 1.95 | 1M | да |
| 🟡 дешёвый | `qwen/qwen3-vl-8b-thinking` | 0.18 | 2.1 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3.5-122b-a10b` | 0.26 | 2.08 | 262k | да |
| 🟡 дешёвый | `aion-labs/aion-2.0` | 0.8 | 1.6 | 131k | да |
| 🟡 дешёвый | `mistralai/devstral-2512` | 0.4 | 2 | 262k | — |
| 🟡 дешёвый | `mistralai/mistral-medium-3` | 0.4 | 2 | 131k | — |
| 🟡 дешёвый | `mistralai/mistral-medium-3.1` | 0.4 | 2 | 131k | — |
| 🟡 дешёвый | `z-ai/glm-4.5v` | 0.6 | 1.8 | 65k | да |
| 🟡 дешёвый | `z-ai/glm-5.3:batch` | 0.45 | 2 | 1M | да |
| 🟡 дешёвый | `z-ai/glm-5` | 0.6 | 1.92 | 204k | да |
| 🟡 дешёвый | `qwen/qwen3-235b-a22b-thinking-2507` | 0.23 | 2.3 | 131k | да |
| 🟡 дешёвый | `qwen/qwen3-30b-a3b-thinking-2507` | 0.2 | 2.4 | 81k | да |
| 🟡 дешёвый | `qwen/qwen3-vl-30b-a3b-thinking` | 0.2 | 2.4 | 262k | да |
| 🟡 дешёвый | `openai/gpt-5.4-mini:batch` | 0.375 | 2.25 | 400k | да |
| 🟡 дешёвый | `deepseek/deepseek-v4-pro-0813` | 0.66 | 1.98 | 1M | да |
| 🟡 дешёвый | `deepseek/deepseek-r1-0528` | 0.5 | 2.15 | 163k | да |
| 🟡 дешёвый | `moonshotai/kimi-k2.5` | 0.45 | 2.25 | 262k | да |
| 🟡 дешёвый | `nvidia/nemotron-3-ultra-550b-a55b` | 0.5 | 2.2 | 262k | да |
| 🟡 дешёвый | `minimax/minimax-m1` | 0.55 | 2.2 | 1M | да |
| 🟡 дешёвый | `openai/o3-mini:batch` | 0.55 | 2.2 | 200k | да |
| 🟡 дешёвый | `openai/o4-mini:batch` | 0.55 | 2.2 | 200k | да |
| 🟡 дешёвый | `amazon/nova-2-lite-v1` | 0.3 | 2.5 | 1M | да |
| 🟡 дешёвый | `google/gemini-2.5-flash` | 0.3 | 2.5 | 1M | да |
| 🟡 дешёвый | `google/gemini-3.5-flash-lite` | 0.3 | 2.5 | 1M | да |
| 🟡 дешёвый | `z-ai/glm-4.5` | 0.6 | 2.2 | 131k | да |
| 🟡 дешёвый | `z-ai/glm-4.7` | 0.6 | 2.2 | 204k | да |
| 🟡 дешёвый | `moonshotai/kimi-k2` | 0.57 | 2.3 | 131k | — |

## 🔴 Для сравнения

Чтобы дешевизна была не абстрактной: верхний край рынка. Наш замер на Opus — три хода разговора
обошлись примерно в 5 центов.

| Уровень | Модель | Вход | Выход | Контекст |
|---|---|---|---|---|
| 🔴 дорогой | `openai/gpt-5.4-pro` | 30 | 180 | 1M |
| 🔴 дорогой | `anthropic/claude-opus-4.1` | 15 | 75 | 200k |
| 🔴 дорогой | `anthropic/claude-sonnet-4` | 3 | 15 | 200k |
| 🟠 средний | `x-ai/grok-4.5` | 2 | 6 | 500k |

## Что с этим делать

**Подключать не вендора, а OpenRouter.** Один адаптер поверх OpenAI-совместимого API — и сразу
весь этот список, включая бесплатные. Смена модели становится сменой **паспорта**, то есть ровно
той сущностью, которая у нас для этого и завелась.

Тогда «нет денег на подписку» решается так: человек берёт бесплатный ключ, ставит паспорт с
`:free`-моделью и работает. Упёрся в суточный предел — меняет паспорт на модель за центы.

Начать стоит с трёх паспортов:

- **рабочая лошадь** — `deepseek/deepseek-v4-flash`: дешевле всех серьёзных, контекст на миллион;
- **нулевая цена** — любая `:free` с инструментами, чтобы проверить путь «совсем без денег»;
- **сверка** — `z-ai/glm-flash-latest` или `qwen/qwen3.7-flash`, чтобы видеть, где поведение
  зависит от вендора, а где от нас.

Чего в этом файле НЕТ намеренно: оценок качества вызова инструментов. Их нельзя взять из прайса —
их надо мерить своими зонами, и это первое, что стоит сделать после второго рантайма.
