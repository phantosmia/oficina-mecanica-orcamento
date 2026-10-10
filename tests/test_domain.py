from datetime import UTC, datetime, timedelta

import pytest

from app.shared.exceptions import DomainError, InvalidTransitionError
from app.quotes.domain.entities import Customer, Quote, QuoteItem
from app.quotes.domain.value_objects import Decider, QuoteStatus

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def quote(**overrides) -> Quote:  # noqa: ANN003
    fields = dict(
        order_id=1, saga_id="s", quote_id="q", token="t", customer=Customer(), notes="",
        services=[QuoteItem("s1", "Revisão", 1, 200.0)], parts=[QuoteItem("p1", "Pastilha", 2, 180.25)],
        status=QuoteStatus.AWAITING_APPROVAL, created_at=NOW, valid_until=NOW + timedelta(days=7),
    )
    fields.update(overrides)
    return Quote(**fields)


def test_totals_come_from_items() -> None:
    q = quote()
    assert (q.labor_total, q.parts_total, q.total) == (200.0, 360.5, 560.5)


def test_needs_items_and_valid_items() -> None:
    with pytest.raises(DomainError):
        quote(services=[], parts=[])
    with pytest.raises(DomainError):
        QuoteItem("x", "X", 0, 10.0)
    with pytest.raises(DomainError):
        QuoteItem("x", "X", 1, -1.0)


@pytest.mark.parametrize("decide", ["approve", "reject"])
def test_decision_is_recorded_once(decide: str) -> None:
    q = quote()
    getattr(q, decide)(Decider.CUSTOMER, NOW)
    assert q.status == (QuoteStatus.APPROVED if decide == "approve" else QuoteStatus.REJECTED)
    assert (q.decided_at, q.decided_by) == (NOW, Decider.CUSTOMER)
    with pytest.raises(InvalidTransitionError, match="já está"):
        q.approve(Decider.ADMIN, NOW)


def test_expired_quote_cannot_be_decided() -> None:
    q = quote(valid_until=NOW - timedelta(seconds=1))
    with pytest.raises(InvalidTransitionError, match="expirou"):
        q.approve(Decider.CUSTOMER, NOW)


def test_cancel_only_awaiting_or_approved() -> None:
    assert quote().cancel(NOW) is True
    approved = quote(status=QuoteStatus.APPROVED)
    assert approved.cancel(NOW) is True and approved.status == QuoteStatus.CANCELLED
    rejected = quote(status=QuoteStatus.REJECTED)
    assert rejected.cancel(NOW) is False and rejected.status == QuoteStatus.REJECTED
    assert quote(status=QuoteStatus.CANCELLED).cancel(NOW) is False
