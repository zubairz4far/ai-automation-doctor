from app.models.schemas import ExecutionFailure
from app.services.diagnoser import DiagnosisEngine
from app.services.patcher import PatchPlanner
from app.services.validator import PatchValidator


def test_rate_limit_patch_is_bounded_and_human_approved():
    failure = ExecutionFailure(
        execution_id="e1",
        workflow_id="w1",
        failed_node="HTTP Request",
        error_message="429 Too Many Requests",
        status_code=429,
    )
    diagnosis = DiagnosisEngine().diagnose(failure)
    proposal = PatchPlanner().propose(failure, diagnosis)

    assert proposal is not None
    assert proposal.requires_human_approval is True
    assert proposal.auto_apply_allowed is False
    assert len(proposal.operations) == 3
    PatchValidator().validate(proposal)
