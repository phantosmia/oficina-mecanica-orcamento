from dataclasses import dataclass
from datetime import datetime

from app.shared.exceptions import DomainError, InvalidTransitionError
from app.quotes.domain.value_objects import Decider, QuoteStatus


@dataclass(frozen=True)
class Customer:
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class QuoteItem:
    """Serviço ou peça do orçamento, com o preço copiado do diagnóstico."""

    item_id: str
    name: str
    quantity: int
    unit_price: float

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.unit_price < 0:
            raise DomainError(f"Item inválido no orçamento: {self.name}.")

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.quantity, 2)


@dataclass
class Quote:
    """Orçamento de uma OS. Os totais são sempre calculados a partir dos
    itens, nunca recebidos prontos."""

    order_id: int
    saga_id: str
    quote_id: str
    token: str
    customer: Customer
    notes: str
    services: list[QuoteItem]
    parts: list[QuoteItem]
    status: QuoteStatus
    created_at: datetime
    valid_until: datetime
    decided_at: datetime | None = None
    decided_by: Decider | None = None
    cancelled_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.services and not self.parts:
            raise DomainError("O orçamento precisa de pelo menos um serviço ou peça.")

    @property
    def labor_total(self) -> float:
        return round(sum(i.subtotal for i in self.services), 2)

    @property
    def parts_total(self) -> float:
        return round(sum(i.subtotal for i in self.parts), 2)

    @property
    def total(self) -> float:
        return round(self.labor_total + self.parts_total, 2)

    def approve(self, by: Decider, now: datetime) -> None:
        self._decide(QuoteStatus.APPROVED, by, now)

    def reject(self, by: Decider, now: datetime) -> None:
        self._decide(QuoteStatus.REJECTED, by, now)

    def cancel(self, now: datetime) -> bool:
        """Compensação. Retorna False quando não há o que cancelar (já
        recusado ou já cancelado): a compensação confirma do mesmo jeito."""
        if self.status not in (QuoteStatus.AWAITING_APPROVAL, QuoteStatus.APPROVED):
            return False
        self.status = QuoteStatus.CANCELLED
        self.cancelled_at = now
        return True

    def _decide(self, target: QuoteStatus, by: Decider, now: datetime) -> None:
        if self.status != QuoteStatus.AWAITING_APPROVAL:
            raise InvalidTransitionError(f"O orçamento já está {self.status.value}.")
        if now > self.valid_until:
            raise InvalidTransitionError("O prazo para responder a este orçamento expirou.")
        self.status = target
        self.decided_at = now
        self.decided_by = by
