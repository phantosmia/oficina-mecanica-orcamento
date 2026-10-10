"""Casos de uso da API: o cliente responde pelo link (token) e o admin
consulta e responde em nome do cliente."""

from datetime import UTC, datetime

from app.shared.email import IEmailNotifier, NullEmailNotifier
from app.shared.events import Envelope
from app.shared.exceptions import InvalidTransitionError, NotFoundError
from app.quotes.application.notifications import send_decision, send_quote_available
from app.quotes.domain.entities import Quote
from app.quotes.domain.ports import IQuoteRepository
from app.quotes.domain.value_objects import Decider, QuoteStatus


class GetQuoteByOrderUseCase:
    def __init__(self, repo: IQuoteRepository) -> None:
        self._repo = repo

    def execute(self, order_id: int) -> Quote:
        quote = self._repo.get_by_order(order_id)
        if quote is None:
            raise NotFoundError("Orçamento", order_id)
        return quote


class GetQuoteByTokenUseCase:
    def __init__(self, repo: IQuoteRepository) -> None:
        self._repo = repo

    def execute(self, token: str) -> Quote:
        quote = self._repo.get_by_token(token)
        if quote is None:
            # Mesma resposta para token inexistente e malformado: não ajuda a adivinhar tokens.
            raise NotFoundError("Orçamento", "token")
        return quote


class DecideQuoteUseCase:
    """Aprovação ou recusa. Publica `OrcamentoAprovado`/`OrcamentoRecusado`
    para o orquestrador, que segue para a cobrança ou compensa."""

    def __init__(self, repo: IQuoteRepository, notifier: IEmailNotifier | None = None) -> None:
        self._repo = repo
        self._notifier = notifier or NullEmailNotifier()

    def execute(self, quote: Quote, approve: bool, by: Decider) -> Quote:
        now = datetime.now(UTC)
        if approve:
            quote.approve(by, now)
        else:
            quote.reject(by, now)
        event = Envelope(
            type="OrcamentoAprovado" if approve else "OrcamentoRecusado",
            payload={"quote_id": quote.quote_id, "total": quote.total, "decided_by": by.value},
            saga_id=quote.saga_id,
            order_id=quote.order_id,
        )
        self._repo.save(quote, expected_status=QuoteStatus.AWAITING_APPROVAL, events=[event])
        send_decision(self._notifier, quote, approve)
        return quote


class ResendQuoteEmailUseCase:
    def __init__(self, repo: IQuoteRepository, notifier: IEmailNotifier, public_base_url: str) -> None:
        self._repo = repo
        self._notifier = notifier
        self._public_base_url = public_base_url

    def execute(self, order_id: int) -> bool:
        quote = GetQuoteByOrderUseCase(self._repo).execute(order_id)
        if quote.status != QuoteStatus.AWAITING_APPROVAL:
            raise InvalidTransitionError(f"O orçamento já está {quote.status.value}; não há o que reenviar.")
        return send_quote_available(self._notifier, quote, self._public_base_url)
