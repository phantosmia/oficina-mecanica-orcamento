from abc import ABC, abstractmethod

from app.shared.events import Envelope
from app.quotes.domain.entities import Quote
from app.quotes.domain.value_objects import QuoteStatus


class AlreadyProcessedError(Exception):
    """A mensagem já tinha sido processada (reentrega): nada foi gravado."""


class IQuoteRepository(ABC):
    @abstractmethod
    def get_by_order(self, order_id: int) -> Quote | None: ...

    @abstractmethod
    def get_by_token(self, token: str) -> Quote | None: ...

    @abstractmethod
    def is_processed(self, message_id: str) -> bool: ...

    @abstractmethod
    def save(self, quote: Quote, expected_status: QuoteStatus | None, events: list[Envelope], message_id: str | None = None) -> None:
        """Grava o orçamento, os eventos (outbox) e, se vier de uma
        mensagem, o registro dela como processada, numa transação.
        `expected_status=None` cria (falha se já existir orçamento para a
        OS); senão só grava se o status salvo ainda for o esperado.
        Levanta `ConcurrencyError` ou `AlreadyProcessedError`."""
        ...

    @abstractmethod
    def reply(self, events: list[Envelope], message_id: str, compensated_saga_id: str | None = None) -> None:
        """Só responde (outbox + mensagem processada), sem mudar orçamento.
        Com `compensated_saga_id`, grava junto um marcador de que aquela saga
        já foi compensada (ver `is_saga_compensated`)."""
        ...

    @abstractmethod
    def is_saga_compensated(self, saga_id: str) -> bool:
        """True se um `CancelarOrcamento` dessa saga chegou antes do orçamento existir."""
        ...
