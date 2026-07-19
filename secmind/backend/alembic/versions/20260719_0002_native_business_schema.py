"""Create the native multi-agent business schema.

Revision ID: 20260719_0002
Revises: 20260715_0001
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0002"
down_revision: str | None = "20260715_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flows_status", "flows", ["status"])
    op.create_index("ix_flows_deleted_at", "flows", ["deleted_at"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_flow_id", "tasks", ["flow_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "subtasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("dependencies_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "position", name="uq_subtasks_task_position"),
    )
    op.create_index("ix_subtasks_task_id", "subtasks", ["task_id"])
    op.create_index("ix_subtasks_status", "subtasks", ["status"])
    op.create_index("ix_subtasks_agent_role", "subtasks", ["agent_role"])

    op.create_table(
        "prompts",
        sa.Column("prompt_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("message_role", sa.String(length=30), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("variables_json", sa.JSON(), nullable=False),
        sa.Column("active_version_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("prompt_key"),
    )
    op.create_index("ix_prompts_category", "prompts", ["category"])
    op.create_index("ix_prompts_message_role", "prompts", ["message_role"])
    op.create_index("ix_prompts_agent_role", "prompts", ["agent_role"])

    op.create_table(
        "prompt_versions",
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("variables_json", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["prompt_key"], ["prompts.prompt_key"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_versions_key_version"),
    )
    op.create_index("ix_prompt_versions_prompt_key", "prompt_versions", ["prompt_key"])
    op.create_index("ix_prompt_versions_checksum", "prompt_versions", ["checksum"])
    op.create_index("ix_prompt_versions_status", "prompt_versions", ["status"])
    op.create_index(
        "uq_prompt_versions_one_active",
        "prompt_versions",
        ["prompt_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "agent_instances",
        sa.Column("instance_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("parent_instance_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=True),
        sa.Column("model_profile", sa.String(length=120), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_instance_id"], ["agent_instances.instance_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.version_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    for column in ("run_id", "flow_id", "role", "status", "task_id", "parent_instance_id"):
        op.create_index(f"ix_agent_instances_{column}", "agent_instances", [column])

    op.create_table(
        "agent_delegations",
        sa.Column("delegation_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("from_agent_instance_id", sa.String(length=36), nullable=False),
        sa.Column("to_role", sa.String(length=100), nullable=False),
        sa.Column("to_agent_instance_id", sa.String(length=36), nullable=True),
        sa.Column("agent_task_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["from_agent_instance_id"],
            ["agent_instances.instance_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_agent_instance_id"],
            ["agent_instances.instance_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("delegation_id"),
    )
    for column in (
        "run_id",
        "flow_id",
        "from_agent_instance_id",
        "to_role",
        "to_agent_instance_id",
        "status",
    ):
        op.create_index(f"ix_agent_delegations_{column}", "agent_delegations", [column])

    op.create_table(
        "agent_messages",
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("from_agent_instance_id", sa.String(length=36), nullable=False),
        sa.Column("to_agent_instance_id", sa.String(length=36), nullable=True),
        sa.Column("to_role", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["from_agent_instance_id"],
            ["agent_instances.instance_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_agent_instance_id"],
            ["agent_instances.instance_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_messages_run_sequence"),
    )
    for column in ("run_id", "flow_id", "from_agent_instance_id", "kind"):
        op.create_index(f"ix_agent_messages_{column}", "agent_messages", [column])

    op.create_table(
        "message_chains",
        sa.Column("chain_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("subtask_id", sa.String(length=36), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=36), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=False),
        sa.Column("model_provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subtask_id"], ["subtasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("chain_id"),
        sa.UniqueConstraint("agent_instance_id"),
    )
    for column in (
        "run_id",
        "flow_id",
        "task_id",
        "subtask_id",
        "agent_role",
        "model_provider",
        "model",
    ):
        op.create_index(f"ix_message_chains_{column}", "message_chains", [column])

    op.create_table(
        "message_entries",
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("chain_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=36), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chain_id"], ["message_chains.chain_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.UniqueConstraint("chain_id", "sequence", name="uq_message_entries_chain_sequence"),
    )
    op.create_index("ix_message_entries_chain_id", "message_entries", ["chain_id"])
    op.create_index("ix_message_entries_role", "message_entries", ["role"])
    op.create_index("ix_message_entries_tool_call_id", "message_entries", ["tool_call_id"])

    op.create_table(
        "mcp_servers",
        sa.Column("server_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("transport", sa.String(length=30), nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("env_refs_json", sa.JSON(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("header_refs_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("protocol_version", sa.String(length=50), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("server_id"),
        sa.UniqueConstraint("name"),
    )
    for column in ("transport", "enabled", "status"):
        op.create_index(f"ix_mcp_servers_{column}", "mcp_servers", [column])

    op.create_table(
        "mcp_capabilities",
        sa.Column("capability_id", sa.String(length=320), nullable=False),
        sa.Column("server_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.server_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("capability_id"),
        sa.UniqueConstraint(
            "server_id", "kind", "name", name="uq_mcp_capabilities_server_kind_name"
        ),
    )
    for column in ("server_id", "kind", "name"):
        op.create_index(f"ix_mcp_capabilities_{column}", "mcp_capabilities", [column])

    op.create_table(
        "tool_calls",
        sa.Column("invocation_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("subtask_id", sa.String(length=36), nullable=True),
        sa.Column("agent_instance_id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=240), nullable=False),
        sa.Column("origin", sa.String(length=30), nullable=False),
        sa.Column("server_id", sa.String(length=120), nullable=True),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("text_result", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subtask_id"], ["subtasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.server_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("invocation_id"),
    )
    for column in (
        "run_id",
        "flow_id",
        "task_id",
        "subtask_id",
        "agent_instance_id",
        "tool_id",
        "origin",
        "server_id",
        "status",
    ):
        op.create_index(f"ix_tool_calls_{column}", "tool_calls", [column])

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=150), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    for column in ("run_id", "flow_id", "sha256"):
        op.create_index(f"ix_artifacts_{column}", "artifacts", [column])

    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("artifact_ref", sa.String(length=64), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_ref"], ["artifacts.artifact_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    for column in ("run_id", "source", "artifact_ref"):
        op.create_index(f"ix_evidence_{column}", "evidence", [column])

    op.create_table(
        "findings",
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("subtask_id", sa.String(length=36), nullable=True),
        sa.Column("rule_id", sa.String(length=150), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subtask_id"], ["subtasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    for column in ("run_id", "subtask_id", "rule_id", "severity", "confidence"):
        op.create_index(f"ix_findings_{column}", "findings", [column])

    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("report_id"),
        sa.UniqueConstraint("run_id", "version", name="uq_reports_run_version"),
    )
    op.create_index("ix_reports_run_id", "reports", ["run_id"])
    op.create_index("ix_reports_status", "reports", ["status"])

    op.create_table(
        "approvals",
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("response_reason", sa.Text(), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("request_id"),
    )
    for column in ("run_id", "step_id", "status"):
        op.create_index(f"ix_approvals_{column}", "approvals", [column])

    op.create_table(
        "llm_calls",
        sa.Column("call_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=36), nullable=True),
        sa.Column("chain_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_ref", sa.Text(), nullable=True),
        sa.Column("response_ref", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["chain_id"], ["message_chains.chain_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("call_id"),
    )
    for column in ("run_id", "flow_id", "provider", "model", "stage", "status"):
        op.create_index(f"ix_llm_calls_{column}", "llm_calls", [column])

    op.create_table(
        "llm_usage",
        sa.Column("usage_id", sa.String(length=36), nullable=False),
        sa.Column("call_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("flow_id", sa.String(length=36), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=36), nullable=True),
        sa.Column("agent_role", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["llm_calls.call_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_instance_id"], ["agent_instances.instance_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("usage_id"),
        sa.UniqueConstraint("call_id"),
    )
    for column in ("run_id", "flow_id", "agent_role", "provider", "model"):
        op.create_index(f"ix_llm_usage_{column}", "llm_usage", [column])


def downgrade() -> None:
    for table_name in (
        "llm_usage",
        "llm_calls",
        "approvals",
        "reports",
        "findings",
        "evidence",
        "artifacts",
        "tool_calls",
        "mcp_capabilities",
        "mcp_servers",
        "message_entries",
        "message_chains",
        "agent_messages",
        "agent_delegations",
        "agent_instances",
        "prompt_versions",
        "prompts",
        "subtasks",
        "tasks",
        "flows",
    ):
        op.drop_table(table_name)
