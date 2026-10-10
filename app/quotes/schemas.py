from datetime import datetime

from pydantic import BaseModel

from app.quotes.domain.value_objects import Decider, QuoteStatus


class QuoteItemRead(BaseModel):
    id: str
    name: str
    quantity: int
    unit_price: float
    subtotal: float


class PublicQuoteRead(BaseModel):
    """O que o cliente vê pelo link: sem token, sem e-mail, sem IDs internos da saga."""

    order_id: int
    status: QuoteStatus
    notes: str
    services: list[QuoteItemRead]
    parts: list[QuoteItemRead]
    labor_total: float
    parts_total: float
    total: float
    valid_until: datetime
    decided_at: datetime | None = None


class QuoteRead(PublicQuoteRead):
    """Visão do admin."""

    quote_id: str
    saga_id: str
    customer_name: str | None
    customer_email: str | None
    approval_url: str
    created_at: datetime
    decided_by: Decider | None = None
    cancelled_at: datetime | None = None


class ResendResult(BaseModel):
    sent: bool
