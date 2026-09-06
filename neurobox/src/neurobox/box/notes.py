"""Первый наш MCP-сервер: агент рассказывает, что ему мешало.

Зачем инструментом, а не разбором ответа: агент общается инструментами, и всё, что нам от него
нужно, должно приходить тем же способом. Разбор текста держался бы на том, что агент не забудет
формат, а забытый формат — это молча потерянная заметка.

Сессию агент не называет: она приходит заголовком, который подставила развёртка. Спрашивать у
агента, где он находится, значило бы доверять его догадке о собственном контексте.
"""

import logging
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from neurobox.box.session import current
from neurobox.db.engine import sessions
from neurobox.db.models import Note, NoteKind

log = logging.getLogger("neurobox.box")

INSTRUCTIONS = """
Здесь ты рассказываешь о том, что мешало тебе работать: ручка отсутствует, ответ непонятен,
описание расходится с поведением, пришлось обходить.

Зови `note_friction` сразу, как упёрся, и продолжай работу. Заметка нужна человеку, чтобы
починить инструмент, а не тебе, чтобы отчитаться: если ты справился обходным путём, это тем
более повод записать — обход и есть то, что чинят.

Не пиши сюда то, что относится к предметной работе (не сошлась проверка, не нашёлся компонент) —
это нормальные результаты, а не затыки.
""".strip()


def build() -> MCPServer:
    server = MCPServer(name="neurobox-notes", instructions=INSTRUCTIONS)

    @server.tool(
        name="note_friction",
        title="Записать затык",
        description=(
            "Сообщить человеку, что мешало работе: нехватка ручки, непонятный ответ, "
            "расхождение описания с поведением, вынужденный обход."
        ),
    )
    async def note_friction(
        what: Annotated[str, Field(description="Что именно мешало, своими словами")],
        where: Annotated[
            str | None, Field(description="Где именно: имя ручки или сервера, если применимо")
        ] = None,
        workaround: Annotated[
            str | None, Field(description="Чем пришлось обойтись, если обошёл")
        ] = None,
    ) -> str:
        session_id = current.get()
        if not session_id:
            # Заголовка нет — значит сервер позвали мимо развёртки. Записывать некуда, и
            # молчаливое согласие оставило бы агента в уверенности, что заметка сохранена.
            return "Заметка не сохранена: неизвестно, к какому разговору её отнести."

        try:
            async with sessions()() as db:
                db.add(
                    Note(
                        session_id=session_id,
                        kind=NoteKind.FRICTION,
                        what=what.strip(),
                        where=(where or "").strip() or None,
                        workaround=(workaround or "").strip() or None,
                    )
                )
                await db.commit()
        except SQLAlchemyError as error:
            # Причина уходит человеку в логи, а агенту — честный ответ: он должен знать, что
            # заметка не дошла, иначе решит, что о затыке уже сообщено.
            log.exception("заметка не сохранена", extra={"session": session_id})
            return f"Заметка не сохранена: {type(error).__name__}. Продолжай работу."

        log.info("затык записан", extra={"session": session_id, "where": where})
        return "Записано. Продолжай работу."

    return server
