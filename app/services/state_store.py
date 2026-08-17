from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models.schemas import (
    ApprovalRecord,
    Diagnosis,
    ExecutionFailure,
    PatchProposal,
    RemediationResponse,
    WorkflowDryRunResponse,
)


class RemediationLeaseError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStateStore:
    """Durable, dependency-free state store for incidents and remediation state."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    proposal_id TEXT UNIQUE,
                    execution_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    failure_json TEXT NOT NULL,
                    diagnosis_json TEXT NOT NULL,
                    proposal_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dry_runs (
                    proposal_id TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    proposal_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    incident_id TEXT,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_timeline_proposal
                    ON timeline(proposal_id, id);

                CREATE TABLE IF NOT EXISTS remediation_runs (
                    proposal_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_until REAL,
                    expected_update_fingerprint TEXT,
                    workflow_version_before TEXT,
                    retry_execution_id TEXT,
                    response_json TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def ping(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 AS ok").fetchone()
        return bool(row and row["ok"] == 1)

    def save_incident(
        self,
        incident_id: str,
        failure: ExecutionFailure,
        diagnosis: Diagnosis,
        proposal: PatchProposal | None,
    ) -> None:
        proposal_id = proposal.proposal_id if proposal else None
        proposal_json = proposal.model_dump_json() if proposal else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    incident_id, proposal_id, execution_id, workflow_id,
                    failure_json, diagnosis_json, proposal_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    proposal_id,
                    failure.execution_id,
                    failure.workflow_id,
                    failure.model_dump_json(),
                    diagnosis.model_dump_json(),
                    proposal_json,
                    _now_iso(),
                ),
            )

    def load_proposal(self, proposal_id: str) -> PatchProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT proposal_json FROM incidents WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if not row or not row["proposal_json"]:
            return None
        return PatchProposal.model_validate_json(row["proposal_json"])

    def load_execution_id(self, proposal_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT execution_id FROM incidents WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return str(row["execution_id"]) if row else None

    def load_incident_id(self, proposal_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT incident_id FROM incidents WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return str(row["incident_id"]) if row else None

    def save_dry_run(self, proposal_id: str, response: WorkflowDryRunResponse) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dry_runs (proposal_id, response_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at
                """,
                (proposal_id, response.model_dump_json(), now),
            )
            connection.execute("DELETE FROM approvals WHERE proposal_id = ?", (proposal_id,))

    def load_dry_run(self, proposal_id: str) -> WorkflowDryRunResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM dry_runs WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        return WorkflowDryRunResponse.model_validate_json(row["response_json"])

    def save_approval(self, proposal_id: str, record: ApprovalRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals (proposal_id, record_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    record_json = excluded.record_json,
                    created_at = excluded.created_at
                """,
                (proposal_id, record.model_dump_json(), _now_iso()),
            )

    def delete_approval(self, proposal_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM approvals WHERE proposal_id = ?", (proposal_id,))

    def load_approval(self, proposal_id: str) -> ApprovalRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM approvals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        return ApprovalRecord.model_validate_json(row["record_json"])

    def append_event(self, proposal_id: str, event_type: str, details: dict[str, Any]) -> None:
        incident_id = self.load_incident_id(proposal_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO timeline (
                    proposal_id, incident_id, event_type, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    incident_id,
                    event_type,
                    json.dumps(details, sort_keys=True, default=str),
                    _now_iso(),
                ),
            )

    def load_timeline(self, proposal_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, details_json, created_at
                FROM timeline
                WHERE proposal_id = ?
                ORDER BY id ASC
                """,
                (proposal_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def claim_remediation(self, proposal_id: str, lease_seconds: int) -> dict[str, Any]:
        owner = str(uuid4())
        now = time.time()
        lease_until = now + max(5, lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remediation_runs WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row and row["response_json"]:
                connection.commit()
                return {**dict(row), "lease_owner": None}
            if row and row["lease_until"] and float(row["lease_until"]) > now:
                connection.rollback()
                raise RemediationLeaseError("A remediation attempt is already in progress.")

            if row:
                connection.execute(
                    """
                    UPDATE remediation_runs
                    SET lease_owner = ?, lease_until = ?, updated_at = ?
                    WHERE proposal_id = ?
                    """,
                    (owner, lease_until, _now_iso(), proposal_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO remediation_runs (
                        proposal_id, stage, lease_owner, lease_until, updated_at
                    ) VALUES (?, 'claimed', ?, ?, ?)
                    """,
                    (proposal_id, owner, lease_until, _now_iso()),
                )
            connection.commit()
        finally:
            connection.close()
        state = self.get_remediation(proposal_id)
        if state is None:
            raise RuntimeError("Unable to load claimed remediation state.")
        state["lease_owner"] = owner
        return state

    def set_remediation_stage(
        self,
        proposal_id: str,
        owner: str,
        stage: str,
        *,
        expected_update_fingerprint: str | None = None,
        workflow_version_before: str | None = None,
        retry_execution_id: str | None = None,
        lease_seconds: int = 30,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE remediation_runs
                SET stage = ?,
                    expected_update_fingerprint = COALESCE(?, expected_update_fingerprint),
                    workflow_version_before = COALESCE(?, workflow_version_before),
                    retry_execution_id = COALESCE(?, retry_execution_id),
                    lease_until = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE proposal_id = ? AND lease_owner = ?
                """,
                (
                    stage,
                    expected_update_fingerprint,
                    workflow_version_before,
                    retry_execution_id,
                    time.time() + max(5, lease_seconds),
                    _now_iso(),
                    proposal_id,
                    owner,
                ),
            )
            if cursor.rowcount != 1:
                raise RemediationLeaseError("Remediation lease was lost before state persistence.")

    def complete_remediation(
        self,
        proposal_id: str,
        owner: str,
        response: RemediationResponse,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE remediation_runs
                SET stage = 'completed', response_json = ?, lease_owner = NULL,
                    lease_until = NULL, last_error = NULL, updated_at = ?
                WHERE proposal_id = ? AND lease_owner = ?
                """,
                (response.model_dump_json(), _now_iso(), proposal_id, owner),
            )
            if cursor.rowcount != 1:
                raise RemediationLeaseError("Remediation lease was lost before completion persistence.")

    def release_remediation(self, proposal_id: str, owner: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE remediation_runs
                SET lease_owner = NULL, lease_until = NULL, last_error = ?, updated_at = ?
                WHERE proposal_id = ? AND lease_owner = ?
                """,
                (error[:1000], _now_iso(), proposal_id, owner),
            )

    def get_remediation(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM remediation_runs WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return dict(row) if row else None

    def load_completed_remediation(self, proposal_id: str) -> RemediationResponse | None:
        state = self.get_remediation(proposal_id)
        if not state or not state.get("response_json"):
            return None
        return RemediationResponse.model_validate_json(state["response_json"])

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            incidents = connection.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"]
            proposals = connection.execute(
                "SELECT COUNT(*) AS n FROM incidents WHERE proposal_id IS NOT NULL"
            ).fetchone()["n"]
            approvals = connection.execute("SELECT COUNT(*) AS n FROM approvals").fetchone()["n"]
            remediations = connection.execute(
                "SELECT COUNT(*) AS n FROM remediation_runs"
            ).fetchone()["n"]
            completed = connection.execute(
                "SELECT COUNT(*) AS n FROM remediation_runs WHERE stage = 'completed'"
            ).fetchone()["n"]
        return {
            "incidents": int(incidents),
            "proposals": int(proposals),
            "approvals": int(approvals),
            "remediations": int(remediations),
            "completed_remediations": int(completed),
        }
