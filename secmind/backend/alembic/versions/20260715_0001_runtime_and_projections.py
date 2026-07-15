"""Create the runtime ledger and event projection tables.

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260715_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_ledger_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_runtime_event_run_sequence"),
    )
    op.create_index("ix_runtime_ledger_events_run_id", "runtime_ledger_events", ["run_id"])
    op.create_index(
        "ix_runtime_ledger_events_event_type",
        "runtime_ledger_events",
        ["event_type"],
    )

    op.create_table(
        "runtime_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_runtime_runs_status", "runtime_runs", ["status"])

    op.create_table(
        "projection_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("scenario", sa.String(length=50), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("active_step_id", sa.String(length=100), nullable=True),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_projection_runs_status", "projection_runs", ["status"])
    op.create_index("ix_projection_runs_scenario", "projection_runs", ["scenario"])

    op.create_table(
        "projection_steps",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "step_id"),
    )
    op.create_index("ix_projection_steps_status", "projection_steps", ["status"])

    op.create_table(
        "projection_approvals",
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("response_reason", sa.Text(), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        "ix_projection_approvals_run_id",
        "projection_approvals",
        ["run_id"],
    )
    op.create_index(
        "ix_projection_approvals_step_id",
        "projection_approvals",
        ["step_id"],
    )
    op.create_index(
        "ix_projection_approvals_status",
        "projection_approvals",
        ["status"],
    )

    op.create_table(
        "projection_findings",
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=True),
        sa.Column("rule_id", sa.String(length=150), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    op.create_index("ix_projection_findings_run_id", "projection_findings", ["run_id"])
    op.create_index("ix_projection_findings_step_id", "projection_findings", ["step_id"])
    op.create_index("ix_projection_findings_rule_id", "projection_findings", ["rule_id"])
    op.create_index("ix_projection_findings_severity", "projection_findings", ["severity"])

    op.create_table(
        "projection_llm_usage",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "provider", "model"),
    )

    op.create_table(
        "projection_offsets",
        sa.Column("projector_name", sa.String(length=100), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("projector_name", "run_id"),
    )


def downgrade() -> None:
    op.drop_table("projection_offsets")
    op.drop_table("projection_llm_usage")
    op.drop_index("ix_projection_findings_severity", table_name="projection_findings")
    op.drop_index("ix_projection_findings_rule_id", table_name="projection_findings")
    op.drop_index("ix_projection_findings_step_id", table_name="projection_findings")
    op.drop_index("ix_projection_findings_run_id", table_name="projection_findings")
    op.drop_table("projection_findings")
    op.drop_index("ix_projection_approvals_status", table_name="projection_approvals")
    op.drop_index("ix_projection_approvals_step_id", table_name="projection_approvals")
    op.drop_index("ix_projection_approvals_run_id", table_name="projection_approvals")
    op.drop_table("projection_approvals")
    op.drop_index("ix_projection_steps_status", table_name="projection_steps")
    op.drop_table("projection_steps")
    op.drop_index("ix_projection_runs_scenario", table_name="projection_runs")
    op.drop_index("ix_projection_runs_status", table_name="projection_runs")
    op.drop_table("projection_runs")
    op.drop_index("ix_runtime_runs_status", table_name="runtime_runs")
    op.drop_table("runtime_runs")
    op.drop_index("ix_runtime_ledger_events_event_type", table_name="runtime_ledger_events")
    op.drop_index("ix_runtime_ledger_events_run_id", table_name="runtime_ledger_events")
    op.drop_table("runtime_ledger_events")
