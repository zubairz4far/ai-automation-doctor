from __future__ import annotations

from app.models.schemas import PatchProposal

FORBIDDEN_PATH_PARTS = (
    "/credentials",
    "/type",
    "/typeVersion",
    "/webhookId",
    "/parameters/jsCode",
    "/parameters/command",
)


class PatchValidationError(ValueError):
    pass


class PatchValidator:
    def __init__(self, max_operations: int = 8):
        self.max_operations = max_operations

    def validate(self, proposal: PatchProposal) -> None:
        if not proposal.requires_human_approval:
            raise PatchValidationError("All workflow mutations must require human approval.")
        if proposal.auto_apply_allowed:
            raise PatchValidationError("Auto-apply is disabled in the baseline safety policy.")
        if len(proposal.operations) > self.max_operations:
            raise PatchValidationError("Patch exceeds the configured operation limit.")

        for operation in proposal.operations:
            lowered = operation.path.lower()
            if any(part.lower() in lowered for part in FORBIDDEN_PATH_PARTS):
                raise PatchValidationError(f"Forbidden mutation path: {operation.path}")
            if not operation.path.startswith("/nodes/"):
                raise PatchValidationError("Baseline patches may only change node parameters/options.")
