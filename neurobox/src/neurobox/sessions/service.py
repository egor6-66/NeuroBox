"""Сессии: создание разговора и прогон реплики через агента.

Здесь сходится всё остальное — каталог даёт рецепт с паспортом, развёртка превращает их в
инструкцию и план серверов, агент выполняет, база помнит.

Оркестратор ничего не решает за агента и ничего не выполняет сам: он собирает задачу, отдаёт её
по общему протоколу и записывает, чем кончилось. Это и есть его работа целиком.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from neurobox.a2a import client
from neurobox.db.models import Author, Message, Run, RunState, Session
from neurobox.mcp.probe import Probe
from neurobox.model.catalog import Catalog
from neurobox.model.entities import Agent, Passport, Recipe
from neurobox.model.refusal import Refusal, RefusalName
from neurobox.model.unfold import Unfolded, unfold


class Missing(Exception):
    """Названного в сессии нет в каталоге. Отдельно от отказов агента: это наша сторона."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.means)
        self.refusal = refusal


def new_id() -> str:
    """Идентификатор сессии он же контекст разговора у агента.

    Придумываем его мы, а не агент: иначе сессию нельзя было бы создать до первой реплики, и
    список пустых разговоров в пульте оказался бы невозможен.
    """
    return str(uuid.uuid4())


def _named(catalog: Catalog, session: Session) -> tuple[Recipe, Passport, Agent]:
    recipe = catalog.recipes.get(session.recipe)
    if recipe is None:
        raise Missing(
            Refusal(
                name=RefusalName.SEED_UNKNOWN,
                means=f"рецепта {session.recipe!r} нет в каталоге",
                where=session.recipe,
            )
        )
    passport = catalog.passports.get(session.passport)
    if passport is None:
        raise Missing(
            Refusal(
                name=RefusalName.SEED_UNKNOWN,
                means=f"паспорта {session.passport!r} нет в каталоге",
                where=session.passport,
            )
        )
    agent = catalog.agents.get(session.agent)
    if agent is None:
        raise Missing(
            Refusal(
                name=RefusalName.AGENT_UNKNOWN,
                means=f"агента {session.agent!r} нет в каталоге",
                where=session.agent,
            )
        )
    return recipe, passport, agent


async def create(
    db: AsyncSession, *, owner_id: str, recipe: str, passport: str, agent: str, title: str | None
) -> Session:
    session = Session(
        id=new_id(), owner_id=owner_id, recipe=recipe, passport=passport, agent=agent, title=title
    )
    db.add(session)
    await db.commit()
    return session


async def by_id(db: AsyncSession, session_id: str, owner_id: str) -> Session | None:
    """Чужую сессию не отдаём даже по точному идентификатору — владелец есть с первого дня."""
    found = await db.execute(
        select(Session).where(Session.id == session_id, Session.owner_id == owner_id)
    )
    return found.scalar_one_or_none()


async def listing(db: AsyncSession, owner_id: str, limit: int = 50) -> list[Session]:
    found = await db.execute(
        select(Session)
        .where(Session.owner_id == owner_id)
        .order_by(Session.updated_at.desc())
        .limit(limit)
    )
    return list(found.scalars().all())


async def history(db: AsyncSession, session_id: str) -> list[Message]:
    found = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    )
    return list(found.scalars().all())


async def runs_of(db: AsyncSession, session_id: str) -> list[Run]:
    found = await db.execute(
        select(Run).where(Run.session_id == session_id).order_by(Run.created_at)
    )
    return list(found.scalars().all())


def _metadata(unfolded: Unfolded) -> dict[str, object]:
    """Что уезжает агенту вместе с задачей: инструкция и серверы рецепта.

    Имена полей наши, протоколу они безразличны — он возит метаданные, не толкуя их. Агент
    решает сам, как ими распорядиться; наше дело — отдать развёртку, а не диктовать исполнение.

    Продолжать разговор или начинать — сюда НЕ входит. Пробовали: оркестратор смотрел в базу и
    говорил агенту. Ошибались — отменённый прогон беседу уже завёл, а по нашим записям она
    выглядела несостоявшейся, и следующий запуск падал на занятом имени. Знать это может только
    тот, кто беседу заводил.
    """
    return {
        "systemPrompt": unfolded.instructions,
        "mcpServers": {plan.seed: plan.server for plan in unfolded.servers},
    }


def _record_usage(run: Run, answer: client.Answer) -> None:
    """Записать расход в момент прогона.

    Именно в момент, а не «посчитаем потом по логам»: цифру называет агент в своём ответе, и
    другого места, где она есть, не существует.

    Расход пишется и у провалившегося прогона: неудачная попытка тоже стоила денег, и
    квота, которая её не видит, врёт.
    """
    usage = answer.usage
    if usage is None:
        return

    run.prompt_tokens = usage.input_tokens
    run.completion_tokens = usage.output_tokens
    run.cache_creation_tokens = usage.cache_creation_tokens
    run.cache_read_tokens = usage.cache_read_tokens
    run.duration_ms = usage.duration_ms
    if usage.cost_usd is not None:
        # Округление вниз до миллионной доли: копить дробные типы в деньгах нельзя, а
        # потерянная миллионная доля цента ни на что не влияет.
        run.cost_micros = int(usage.cost_usd * 1_000_000)


async def begin(
    db: AsyncSession,
    session: Session,
    catalog: Catalog,
    probes: dict[str, Probe],
    text: str,
) -> tuple[Run, Agent, dict[str, object]]:
    """Записать реплику и завести прогон ДО обращения к агенту.

    Именно до: упавший посреди разговора сервис обязан оставить след с состоянием «работает», а
    не тишину, по которой ничего не восстановить.
    """
    recipe, passport, agent = _named(catalog, session)
    unfolded = unfold(catalog, recipe, passport, probes)

    db.add(Message(session_id=session.id, author=Author.HUMAN, text=text))
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        state=RunState.WORKING,
        unfolded=unfolded.model_dump(mode="json"),
    )
    db.add(run)
    session.updated_at = datetime.now(UTC)
    await db.commit()

    return run, agent, _metadata(unfolded)


async def finish(db: AsyncSession, run: Run, answer: client.Answer) -> Run:
    """Применить ответ агента к уже заведённому прогону."""
    run.finished_at = datetime.now(UTC)
    _record_usage(run, answer)

    if answer.ok:
        run.state = RunState.COMPLETED
        db.add(
            Message(session_id=run.session_id, author=Author.AGENT, text=answer.text, run_id=run.id)
        )
    else:
        run.state = RunState.FAILED
        first = answer.refusals[0] if answer.refusals else None
        run.refusal = first.name.value if first else None
        run.means = first.means if first else None
        # Текст провалившегося прогона тоже сохраняется репликой: агент часто объясняет причину
        # именно там, и прятать её от истории значило бы прятать её от человека.
        if answer.text:
            db.add(
                Message(
                    session_id=run.session_id, author=Author.AGENT, text=answer.text, run_id=run.id
                )
            )

    await _touch(db, run.session_id)
    await db.commit()
    return run


async def cancelled(db: AsyncSession, run: Run, means: str) -> Run:
    """Отметить прогон отменённым. Отмена не отказ агента — это решение человека."""
    run.state = RunState.CANCELED
    run.refusal = RefusalName.CANCELED.value
    run.means = means
    run.finished_at = datetime.now(UTC)
    await _touch(db, run.session_id)
    await db.commit()
    return run


async def _touch(db: AsyncSession, session_id: str) -> None:
    found = await db.execute(select(Session).where(Session.id == session_id))
    session = found.scalar_one_or_none()
    if session is not None:
        session.updated_at = datetime.now(UTC)


async def run_by_id(db: AsyncSession, run_id: str) -> Run | None:
    found = await db.execute(select(Run).where(Run.id == run_id))
    return found.scalar_one_or_none()


async def say(
    db: AsyncSession,
    session: Session,
    catalog: Catalog,
    probes: dict[str, Probe],
    text: str,
) -> Run:
    """Реплика от начала до конца, не отпуская управления.

    Остаётся ради тестов и прямых сценариев; ручка сессий работает через фоновый прогон.
    """
    run, agent, metadata = await begin(db, session, catalog, probes, text)
    answer = await client.send(
        agent.url, text, metadata=metadata, context_id=session.id, headers=agent.headers or None
    )
    return await finish(db, run, answer)
