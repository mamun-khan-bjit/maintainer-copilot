from structlog.testing import capture_logs

from maintainer_copilot.redact import fingerprint
from maintainer_copilot.triage import TriageResult, validate

SECRET_TEXT = "contact me at alice@example.com, token ghp_abc123"


def test_fingerprint_hides_text_but_is_stable():
    first = fingerprint(SECRET_TEXT)
    assert "alice" not in str(first)
    assert first == fingerprint(SECRET_TEXT)
    assert first["chars"] == len(SECRET_TEXT)


def test_evidence_warning_does_not_log_issue_text():
    result = TriageResult(
        kind="bug", summary="s", labels=[], missing_info=[], evidence_quote=SECRET_TEXT, confidence=0.5
    )
    with capture_logs() as logs:
        validate(result, "a title", "a body that does not contain the quote", allowed_labels=[])

    assert logs, "expected a triage.evidence_not_found warning"
    assert "alice@example.com" not in str(logs)
    assert "ghp_abc123" not in str(logs)
