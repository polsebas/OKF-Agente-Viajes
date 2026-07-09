from pydantic import BaseModel
from enum import Enum


class ValidationSeverity(str, Enum):
    ERROR = "error"      # blocks the write
    WARNING = "warning"  # logged, does not block


class ValidationIssue(BaseModel):
    rule_name: str
    severity: ValidationSeverity
    concept_id: str
    message: str


class ValidationResult(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = []
