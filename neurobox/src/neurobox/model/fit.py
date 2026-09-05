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

from neurobox.model.entities import Demands, Passport, Seed


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


def check(seeds: list[Seed], passport: Passport) -> Verdict:
    """Вердикт по набору семян. Худший исход побеждает, но не блокирует."""
    notes = [check_seed(seed, passport) for seed in seeds]
    hints = [seed.needs.hint for seed in seeds if seed.needs.hint]

    if any(note.fit is Fit.WEAK for note in notes):
        overall = Fit.WEAK
    elif notes and all(note.fit is Fit.UNKNOWN for note in notes):
        overall = Fit.UNKNOWN
    else:
        overall = Fit.FITS

    return Verdict(fit=overall, notes=notes, hints=hints)
