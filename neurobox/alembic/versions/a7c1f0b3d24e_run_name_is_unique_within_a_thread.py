"""имя хода уникально внутри потока, а не на весь бокс

Имя хода (`runId` протокола) придумывает ПОТРЕБИТЕЛЬ. Пока ключ был одним лишь именем, `ход-1`
во втором разговоре падал нарушением уникальности — то есть пятисотой, и виноватым выглядел тот,
кто назвал ход так же, как называл его в другом потоке. А это норма, а не совпадение.

Ключ становится составным: поток и имя хода.

Revision ID: a7c1f0b3d24e
Revises: 1539ed052d21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c1f0b3d24e"
down_revision: str | None = "1539ed052d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("runs_pkey", "runs", type_="primary")
    op.create_primary_key("runs_pkey", "runs", ["session_id", "id"])


def downgrade() -> None:
    # Обратно ключ сузится только если имена ходов и так уникальны на весь бокс. Если нет —
    # база честно откажет, и это лучше, чем молча выбросить чужой ход.
    op.drop_constraint("runs_pkey", "runs", type_="primary")
    op.create_primary_key("runs_pkey", "runs", ["id"])
