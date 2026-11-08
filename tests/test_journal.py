from datetime import UTC, datetime

import pytest

from ata.domain import Action, DecisionRecord
from ata.journal import DecisionJournal


def make_record(snapshot_id: str = "snapshot-001") -> DecisionRecord:
    return DecisionRecord(
        action=Action.STAY_CASH,
        reason_code="NO_VALIDATED_EDGE",
        rationale="No validated strategy is currently authorized.",
        snapshot_id=snapshot_id,
        strategy_version="research-baseline-0",
        created_at=datetime(2026, 11, 8, 12, 0, tzinfo=UTC),
    )


def test_append_and_replay_records(tmp_path) -> None:
    journal = DecisionJournal(tmp_path / "events" / "decisions.jsonl")
    first = make_record("snapshot-001")
    second = make_record("snapshot-002")

    journal.append(first)
    journal.append(second)

    records = journal.read_all()
    assert len(records) == 2
    assert records[0]["decision_id"] == first.decision_id
    assert records[1]["snapshot_id"] == "snapshot-002"
    assert records[0]["action"] == "STAY_CASH"


def test_missing_journal_returns_empty_list(tmp_path) -> None:
    assert DecisionJournal(tmp_path / "missing.jsonl").read_all() == []


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        DecisionRecord(
            action=Action.STAY_CASH,
            reason_code="TEST",
            rationale="test",
            snapshot_id="snapshot",
            strategy_version="v0",
            created_at=datetime(2026, 11, 8, 12, 0),
        )


def test_invalid_action_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="action must be an Action"):
        DecisionRecord(
            action="BUY_BTC",  # type: ignore[arg-type]
            symbol="BTCUSDT",
            reason_code="TEST",
            rationale="test",
            snapshot_id="snapshot",
            strategy_version="v0",
        )


def test_buy_action_requires_matching_symbol() -> None:
    with pytest.raises(ValueError, match="BUY_BTC requires"):
        DecisionRecord(
            action=Action.BUY_BTC,
            symbol="ETHUSDT",
            reason_code="TEST",
            rationale="test",
            snapshot_id="snapshot",
            strategy_version="v0",
        )
