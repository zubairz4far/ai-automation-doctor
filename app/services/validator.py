from __future__ import annotations

from app.models.schemas import PatchProposal

ALLOWED_OPTION_PATHS = frozenset(
    {
        "retryOnFail",
        "maxTries",
        "waitBetweenTries",
    }
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
        if not proposal.operations:
            raise PatchValidationError("Patch proposal contains no operations.")
        if len(proposal.operations) > self.max_operations:
            raise PatchValidationError("Patch exceeds the configured operation limit.")

        targets: set[str] = set()
        for operation in proposal.operations:
            parts = operation.path.split("/")
            if len(parts) != 6 or parts[0] != "":
                raise PatchValidationError(f"Unsupported mutation path: {operation.path}")
            _, root, node_segment, parameters, options, option_name = parts
            if root != "nodes" or parameters != "parameters" or options != "options":
                raise PatchValidationError(f"Unsupported mutation path: {operation.path}")
            if not node_segment:
                raise PatchValidationError("Patch operation is missing a target node.")
            if option_name not in ALLOWED_OPTION_PATHS:
                raise PatchValidationError(f"Forbidden mutation path: {operation.path}")
            self._validate_value(option_name, operation.value)
            targets.add(node_segment)

        if len(targets) != 1:
            raise PatchValidationError("A baseline patch may target exactly one workflow node.")

    @staticmethod
    def _validate_value(option_name: str, value: object) -> None:
        if option_name == "retryOnFail":
            if value is not True:
                raise PatchValidationError("retryOnFail may only be enabled, not disabled.")
            return

        if type(value) is not int:
            raise PatchValidationError(f"{option_name} must be an integer.")
        if option_name == "maxTries" and not 1 <= value <= 5:
            raise PatchValidationError("maxTries must be between 1 and 5.")
        if option_name == "waitBetweenTries" and not 250 <= value <= 60_000:
            raise PatchValidationError("waitBetweenTries must be between 250 and 60000 ms.")
