"""Таблицы. Здесь живёт только то, что переживает рестарт.

Каталог (паспорта, семена, рецепты) в базе НЕ хранится — он приходит слоями и перечитывается с
диска. Здесь то, что породила работа: сессии, сообщения, прогоны и их цена.

Имена сессии и прогона взяты у протокола, а не выдуманы: в A2A разговор зовётся контекстом, а
отдельная задача внутри него — задачей. Совпадение полное, поэтому свою идентичность мы не
изобретаем, а принимаем протокольную — иначе пришлось бы держать две и сводить их между собой.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, DateTime


class Base(DeclarativeBase):
    # JSONB в постгресе, обычный JSON в sqlite под тестами: разные диалекты, одна модель.
    type_annotation_map = {dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")}


def now() -> datetime:
    return datetime.now(UTC)


def enum_column(kind: type[StrEnum]) -> Enum:
    """Перечисление, которое ВОЗВРАЩАЕТСЯ перечислением, а не строкой.

    Хранить его простой строкой дешевле, но тогда аннотация `Mapped[Author]` врёт: из базы
    приходит `str`, и сравнение по тождеству молча даёт ложь, а проверка типов этого не видит.
    `native_enum=False` — значение остаётся текстом в базе (миграции проще), но слой отображения
    приводит его обратно к члену перечисления.
    """
    return Enum(kind, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])


class Author(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class RunState(StrEnum):
    """Состояния прогона. Перечень протокольный, сведённый к тому, что нам нужно различать."""

    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class Session(Base):
    """Разговор: чем думаем, с чем работаем, кому принадлежит."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Идентификатор контекста A2A. Свой не заводим — иначе их было бы два."""

    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    """Владелец. Появился с первого дня: приписать его живым сессиям потом значило бы выбирать,
    кому они принадлежат, и ответ был бы неправдой."""

    title: Mapped[str | None] = mapped_column(String(200), default=None)

    recipe: Mapped[str] = mapped_column(String(120))
    passport: Mapped[str] = mapped_column(String(120))
    agent: Mapped[str] = mapped_column(String(120))
    """Имена, а не содержимое: рецепт и паспорт живут слоями и меняются, сессия ссылается."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Run.created_at"
    )


class Message(Base):
    """Реплика в разговоре. Хранится и человеческая, и агентская — история одна на двоих."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )

    author: Mapped[Author] = mapped_column(enum_column(Author))
    text: Mapped[str] = mapped_column(Text)

    run_id: Mapped[str | None] = mapped_column(String(64), default=None)
    """Прогон, породивший реплику. У человеческой пусто."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    session: Mapped[Session] = relationship(back_populates="messages")


class Run(Base):
    """Один прогон агента: чем кончился и во сколько обошёлся."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Идентификатор задачи A2A."""

    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )

    state: Mapped[RunState] = mapped_column(enum_column(RunState), default=RunState.WORKING)

    refusal: Mapped[str | None] = mapped_column(String(64), default=None)
    """Имя отказа, если прогон не удался. По имени пульт объясняет человеку, что случилось."""

    means: Mapped[str | None] = mapped_column(Text, default=None)
    """Человеческое объяснение отказа — то же поле, что у отказов каталога."""

    unfolded: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Чем прогон кормили: инструкция и план серверов на момент запуска. Рецепт и семена
    меняются, а разбор прошлого прогона должен опираться на то, что было тогда, а не сейчас."""

    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=None)

    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    """Кэш считается отдельно: на коротком вопросе его бывает на порядок больше обычных
    токенов, и учёт без него показывал бы копейки там, где потрачено ощутимо."""

    cost_micros: Mapped[int | None] = mapped_column(Integer, default=None)
    """Цена в миллионных долях доллара: целое, потому что деньги в дробных типах накапливают
    ошибку. Не заявлено — остаётся пустым, а не изображает ноль. На подписке это не счёт, а
    оценка, которую называет сам агент."""

    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    """Сколько агент думал по его собственному счёту — не то же, что время нашего запроса."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    session: Mapped[Session] = relationship(back_populates="runs")


# Списки сессий владельца всегда идут свежими сверху — под это и индекс.
Index("ix_sessions_owner_updated", Session.owner_id, Session.updated_at.desc())

__all__ = ["Author", "Base", "Message", "Run", "RunState", "Session", "enum_column", "func", "now"]
