"""Сверка семени с паспортом — подсказка, а не гейт.

Исходов три, и ни один не запрещает запуск. `FITS` — подходит. `WEAK` — заявленный минимум
не выполняется, но решать человеку. `UNKNOWN` — сравнивать не с чем: паспорт не заявил
характеристику или семя не заявило требований.

Третий исход существует отдельно от `WEAK` намеренно: «паспорт не сказал» означает незнание,
а не несоответствие. Сервис, отказавший из-за незнакомой модели, был бы хуже, чем сервис без
проверки вовсе.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from neurobox.model.entities import Demands, Passport, Seed, ServerSeed


class Fit(StrEnum):
    FITS = "fits"
    WEAK = "weak"
    UNKNOWN = "unknown"


class Note(BaseModel):
    """Одно замечание сверки — на человека, не на машину."""

    seed: str
    fit: Fit
    means: str


class Verdict(BaseModel):
    fit: Fit
    notes: list[Note] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    """Непроверяемые пожелания семян. Показываются как есть и ни на что не влияют."""

    weight_tokens: int = 0
    """Во сколько примерно обходится присутствие опрошенных серверов в контексте.

    Цифра ЗАМЕРЕНА при опросе, а не заявлена автором семени: он её знать не может, а мы
    можем. Показывается всегда, даже когда вердикт «подходит» — сколько окна съедено ещё до
    первого слова человека, решать ему.
    """


def _weak_points(demands: Demands, passport: Passport) -> list[str]:
    """Чем паспорт НЕ дотягивает до требований. Незаявленное молчит, а не считается провалом."""
    short: list[str] = []

    if demands.context is not None and passport.context is not None:
        if passport.context < demands.context:
            short.append(f"окно модели {passport.context} меньше требуемых {demands.context}")

    if demands.tools and passport.tools is False:
        short.append("нужен вызов инструментов, а модель его не умеет")

    if demands.structured_output and passport.structured_output is False:
        short.append("нужен структурированный ответ, а модель его не обещает")

    return short


def _comparable(demands: Demands, passport: Passport) -> bool:
    """Есть ли хоть одна пара «требование + его двойник в паспорте»."""
    return (
        (demands.context is not None and passport.context is not None)
        or (demands.tools is not None and passport.tools is not None)
        or (demands.structured_output is not None and passport.structured_output is not None)
    )


def check_seed(seed: Seed, passport: Passport) -> Note:
    short = _weak_points(seed.needs.minimum, passport)
    if short:
        return Note(seed=seed.name, fit=Fit.WEAK, means="; ".join(short))

    if not _comparable(seed.needs.minimum, passport):
        return Note(
            seed=seed.name,
            fit=Fit.UNKNOWN,
            means="сравнивать не с чем: требования или характеристики модели не заявлены",
        )

    return Note(seed=seed.name, fit=Fit.FITS, means="минимум выполняется")


def check(
    seeds: list[Seed], passport: Passport, weights: dict[str, int] | None = None
) -> Verdict:
    """Вердикт по набору семян. Худший исход побеждает, но не блокирует.

    `weights` — замеренный опросом вес описания серверов. Не передан (опроса ещё не было) —
    считается только заявленное: незамеренное молчит, а не изображает ноль.
    """
    measured = weights or {}
    notes = [check_seed(seed, passport) for seed in seeds]
    hints = [seed.needs.hint for seed in seeds if seed.needs.hint]

    total = sum(measured.get(seed.name, 0) for seed in seeds if isinstance(seed, ServerSeed))

    # Описание, не влезающее в окно целиком, ломает прогон ещё до первого слова человека.
    # Порог здесь ровно один и не выдуман: сравнение с самим окном. Придумывать «а если
    # больше половины» значило бы поставить в проверку число, взятое из воздуха.
    if passport.context is not None and total >= passport.context:
        notes.append(
            Note(
                seed="—",
                fit=Fit.WEAK,
                means=(
                    f"описание серверов ≈{total} токенов не оставляет места в окне "
                    f"{passport.context}"
                ),
            )
        )

    if any(note.fit is Fit.WEAK for note in notes):
        overall = Fit.WEAK
    elif notes and all(note.fit is Fit.UNKNOWN for note in notes):
        overall = Fit.UNKNOWN
    else:
        overall = Fit.FITS

    return Verdict(fit=overall, notes=notes, hints=hints, weight_tokens=total)
