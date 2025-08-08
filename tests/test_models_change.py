"""Tests for the Change dataclass."""

from datetime import datetime

from summarizer.common.models import Change, ChangeType


def test_change_model_basics() -> None:
    """Ensure Change dataclass stores attributes as expected."""
    ch = Change(
        id="1",
        type=ChangeType.COMMIT,
        timestamp=datetime(2024, 7, 1, 12, 0, 0),
        repo_full_name="owner/repo",
        title="Fix bug",
        url="https://example/commit/sha",
        summary="Fixes null pointer",
        metadata={"sha": "deadbeef"},
    )
    assert ch.type is ChangeType.COMMIT
    assert ch.metadata["sha"] == "deadbeef"
