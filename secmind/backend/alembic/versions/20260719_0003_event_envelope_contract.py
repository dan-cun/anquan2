"""Add versioned event-envelope context to the runtime ledger.

Revision ID: 20260719_0003
Revises: 20260719_0002
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0003"
down_revision: str | None = "20260719_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runtime_ledger_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "schema_version",
                sa.String(length=20),
                nullable=False,
                server_default="1.0",
            )
        )
        batch_op.add_column(sa.Column("flow_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("correlation_id", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("causation_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("decision_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("agent_instance_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("task_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("tool_invocation_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "visibility",
                sa.String(length=20),
                nullable=False,
                server_default="public",
            )
        )

    for column in (
        "flow_id",
        "correlation_id",
        "decision_id",
        "agent_instance_id",
        "tool_invocation_id",
    ):
        op.create_index(
            f"ix_runtime_ledger_events_{column}",
            "runtime_ledger_events",
            [column],
        )


def downgrade() -> None:
    for column in (
        "tool_invocation_id",
        "agent_instance_id",
        "decision_id",
        "correlation_id",
        "flow_id",
    ):
        op.drop_index(f"ix_runtime_ledger_events_{column}", table_name="runtime_ledger_events")

    with op.batch_alter_table("runtime_ledger_events") as batch_op:
        for column in (
            "visibility",
            "tool_invocation_id",
            "task_id",
            "agent_instance_id",
            "decision_id",
            "causation_id",
            "correlation_id",
            "flow_id",
            "schema_version",
        ):
            batch_op.drop_column(column)
