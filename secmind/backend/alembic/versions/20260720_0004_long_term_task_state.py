"""Create Skill, Todo, Notes, and context snapshot tables.

Revision ID: 20260720_0004
Revises: 20260719_0003
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0004"
down_revision: str | None = "20260719_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("compatible_roles_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("skills", ("checksum", "source", "enabled"))

    op.create_table(
        "skill_loads",
        sa.Column("load_id", sa.String(36), primary_key=True),
        sa.Column("skill_id", sa.String(120), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("agent_instance_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
    )
    _indexes(
        "skill_loads",
        ("skill_id", "run_id", "flow_id", "agent_instance_id", "unloaded_at"),
    )

    op.create_table(
        "task_todos",
        sa.Column("todo_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("agent_instance_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
    )
    _indexes(
        "task_todos",
        ("run_id", "flow_id", "task_id", "agent_instance_id", "status", "priority"),
    )

    op.create_table(
        "task_notes",
        sa.Column("note_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("agent_instance_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
    )
    _indexes("task_notes", ("run_id", "flow_id", "agent_instance_id", "kind", "status"))

    op.create_table(
        "context_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("flow_id", sa.String(36), nullable=False),
        sa.Column("agent_instance_id", sa.String(36), nullable=True),
        sa.Column("source_from_sequence", sa.Integer(), nullable=False),
        sa.Column("source_to_sequence", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens_before", sa.Integer(), nullable=False),
        sa.Column("estimated_tokens_after", sa.Integer(), nullable=False),
        sa.Column("narrative_summary", sa.Text(), nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
    )
    _indexes("context_snapshots", ("run_id", "flow_id", "agent_instance_id", "source_to_sequence"))


def downgrade() -> None:
    for table in ("context_snapshots", "task_notes", "task_todos", "skill_loads", "skills"):
        op.drop_table(table)
