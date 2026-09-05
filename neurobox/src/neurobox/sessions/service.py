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


def _metadata(unfolded: Unfolded, *, resume: bool) -> dict[str, object]:
    """Что уезжает агенту вместе с задачей: инструкция, серверы рецепта и продолжение беседы.

    Имена полей наши, протоколу они безразличны — он возит метаданные, не толкуя их.

    `resume` говорит агенту, продолжать разговор или начинать. Это НЕ вмешательство в его
    работу: надёжно знать, был ли уже прогон в этом контексте, может только тот, у кого есть
    долговременная память, а она здесь. Агент, переживший рестарт, о прошлом разговоре не
    вспомнит и начнёт молча заново — а человек увидит собеседника с потерянной памятью и не
    поймёт, почему.
    """
    return {
        "systemPrompt": unfolded.instructions,
        "mcpServers": {plan.seed: plan.server for plan in unfolded.servers},
        "resume": resume,
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


async def say(
    db: AsyncSession,
    session: Session,
    catalog: Catalog,
    probes: dict[str, Probe],
    text: str,
) -> Run:
    """Отправить реплику и дождаться ответа агента.

    Прогон записывается ДО обращения к агенту: если сервис упадёт посреди разговора, останется
    след с состоянием «работает», а не тишина, по которой ничего не восстановить.
    """
    recipe, passport, agent = _named(catalog, session)
    unfolded = unfold(catalog, recipe, passport, probes)

    # Беседа продолжается, если в ней уже был удавшийся прогон. Провалившийся не считается:
    # у агента после него ничего не осталось, и «продолжи» упёрлось бы в ненайденную беседу.
    previous = await db.execute(
        select(Run.id)
        .where(Run.session_id == session.id, Run.state == RunState.COMPLETED)
        .limit(1)
    )
    resume = previous.first() is not None

    db.add(Message(session_id=session.id, author=Author.HUMAN, text=text))
    run = Run(
        id=str(uuid.uuid4()),
        session_id=session.id,
        state=RunState.WORKING,
        unfolded=unfolded.model_dump(mode="json"),
    )
    db.add(run)
    await db.commit()

    answer = await client.send(
        agent.url,
        text,
        metadata=_metadata(unfolded, resume=resume),
        context_id=session.id,
        headers=agent.headers or None,
    )

    run.finished_at = datetime.now(UTC)
    _record_usage(run, answer)
    if answer.ok:
        run.state = RunState.COMPLETED
        db.add(Message(session_id=session.id, author=Author.AGENT, text=answer.text, run_id=run.id))
    else:
        run.state = RunState.FAILED
        first = answer.refusals[0] if answer.refusals else None
        run.refusal = first.name.value if first else None
        run.means = first.means if first else None
        # Текст провалившегося прогона тоже сохраняется репликой: агент часто объясняет причину
        # именно там, и прятать её от истории значило бы прятать её от человека.
        if answer.text:
            db.add(
                Message(session_id=session.id, author=Author.AGENT, text=answer.text, run_id=run.id)
            )

    session.updated_at = datetime.now(UTC)
    await db.commit()
    return run
