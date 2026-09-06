"""Сущности модели: паспорт, семя, рецепт.

Паспорт — КТО агент. Семя — минимальный именованный вход, разворачивающийся во много.
Рецепт — С ЧЕМ агент работает, то есть комбинация семян. Паспорт в рецепте не называется:
человек выбирает отдельно, кем работать, и отдельно, над чем.

Разбор понятий — в корневом README, обоснования — в корневом FAQ.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from neurobox.model.refusal import Refusal


class Layer(StrEnum):
    """Слой, из которого пришёл элемент. Каждый следующий перекрывает предыдущий."""

    BUILTIN = "builtin"
    """Наши собственные серверы. Самый нижний слой: они есть всегда, но любой слой выше их
    перекрывает — привилегий у них нет."""

    IMAGE = "image"
    FILE = "file"
    DB = "db"


class Demands(BaseModel):
    """Чего семя требует от модели.

    Только то, у чего есть настоящий двойник в паспорте — иначе это пожелание, а не
    требование, и ему место в `hint`. Ни одно поле не обязательно: перечень моделей
    открытый, и автор семени не может знать, на чём его запустят.
    """

    context: int | None = None
    """Минимальное окно модели в токенах."""

    tools: bool | None = None
    """Нужен вызов инструментов."""

    structured_output: bool | None = None
    """Нужен структурированный ответ."""


class Needs(BaseModel):
    minimum: Demands = Field(default_factory=Demands)
    recommended: Demands = Field(default_factory=Demands)

    hint: str | None = None
    """Непроверяемое пожелание («нужна умная модель»). Названо подсказкой намеренно:
    смешивать его с проверяемым нельзя, иначе обесценится и оно, и проверка рядом."""


class Passport(BaseModel):
    """Чем агент думает."""

    name: str
    layer: Layer

    provider: str
    model: str

    description: str | None = None

    context: int | None = None
    """Окно модели. Не заявлено — сверка с требованиями семени промолчит, а не откажет."""

    tools: bool | None = None
    structured_output: bool | None = None

    max_tokens: int | None = None
    temperature: float | None = None


class ServerSeed(BaseModel):
    """Семя-сервер: адрес разворачивается в перечень тулзов и инструкцию при опросе."""

    kind: Literal["server"] = "server"

    name: str
    layer: Layer

    description: str | None = None
    needs: Needs = Field(default_factory=Needs)

    server: dict[str, Any]
    """Запись в исходном формате MCP — переносится копированием между инструментами."""

    refusals: list[Refusal] = Field(default_factory=list)
    """Отказы, накопленные при чтении: например, не нашлась переменная окружения.
    Семя с отказом остаётся видимым — молча пропасть из списка оно не имеет права."""


class KnowledgeSeed(BaseModel):
    """Семя-знание: именованный кусок инструкции, задаваемый один раз и переиспользуемый."""

    kind: Literal["knowledge"] = "knowledge"

    name: str
    layer: Layer

    description: str | None = None
    needs: Needs = Field(default_factory=Needs)

    text: str


Seed = ServerSeed | KnowledgeSeed


class Agent(BaseModel):
    """Кто выполняет прогон. В конфиге — имя и адрес, остальное вычитывается из визитки.

    Агент непрозрачен по построению: что у него внутри — своя модель, чужой сервис, локальный
    CLI — оркестратора не касается. Он знает адрес и читает визитку, как читает перечень тулзов
    у MCP-сервера.
    """

    name: str
    layer: Layer

    url: str
    description: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    refusals: list[Refusal] = Field(default_factory=list)
    """Отказы чтения — например, не нашлась переменная окружения для токена."""


class Recipe(BaseModel):
    """С чем агент работает — список имён семян и ничего кроме.

    Рецепт не знает природы семени: поднять сервер или подложить текст в инструкцию решает
    сервис. Поэтому вынос семени на другой слой рецепту незаметен.
    """

    name: str
    layer: Layer

    description: str | None = None
    seeds: list[str] = Field(default_factory=list)
