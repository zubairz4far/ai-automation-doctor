import json
from pathlib import Path

from app.core.config import Settings
from app.models.schemas import ExecutionFailure
from app.services.incidents import IncidentService
from app.services.state_store import RemediationLeaseError, SQLiteStateStore

FIXTURE = Path(__file__).parent / "fixtures/http_retry_workflow.json"


def test_incident_dry_run_and_approval_survive_service_restart(tmp_path):
    db_path = tmp_path / "doctor.db"
    settings = Settings(state_db_path=str(db_path))
    first = IncidentService(settings=settings, store=SQLiteStateStore(str(db_path)))

    analysis = first.analyze(
        ExecutionFailure(
            execution_id="restart-execution",
            workflow_id="workflow-7",
            failed_node="CRM / HTTP Request",
            error_message="429 Too Many Requests",
            status_code=429,
        )
    )
    assert analysis.patch is not None
    proposal_id = analysis.patch.proposal_id
    workflow = json.loads(FIXTURE.read_text())
    first.dry_run(proposal_id, workflow)
    first.approve(proposal_id, "operator", "restart durability test")

    restarted = IncidentService(settings=settings, store=SQLiteStateStore(str(db_path)))

    assert restarted.get_proposal(proposal_id).proposal_id == proposal_id
    assert restarted.get_execution_id(proposal_id) == "restart-execution"
    assert restarted.get_dry_run(proposal_id).workflow_version_id == "version-abc"
    assert restarted.get_approval(proposal_id).approved_by == "operator"

    timeline = restarted.timeline(proposal_id)
    assert [event.event_type for event in timeline.events] == [
        "diagnosed",
        "dry_run_validated",
        "approved",
    ]
    stats = restarted.stats()
    assert stats.incidents == 1
    assert stats.proposals == 1
    assert stats.approvals == 1


def test_remediation_lease_blocks_concurrent_claims(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "doctor.db"))
    first = store.claim_remediation("proposal-1", lease_seconds=30)

    try:
        store.claim_remediation("proposal-1", lease_seconds=30)
    except RemediationLeaseError:
        pass
    else:
        raise AssertionError("second remediation claim should have been rejected")

    store.release_remediation("proposal-1", str(first["lease_owner"]), "test release")
    second = store.claim_remediation("proposal-1", lease_seconds=30)
    assert second["lease_owner"] != first["lease_owner"]
