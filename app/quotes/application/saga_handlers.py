"""Participação do Orçamento na saga da OS (docs/saga.md, no repositório
oficina-mecanica-fiap): `GerarOrcamento` e a compensação `CancelarOrcamento`.

Mesmas regras dos outros participantes: idempotência por `message_id`,
comando reenviado devolve a mesma resposta sem repetir o efeito, falha de
negócio vira evento (`OrcamentoFalhou`), exceção só para falha técnica.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.shared.email import IEmailNotifier, NullEmailNotifier
from app.shared.events import Envelope
from app.shared.exceptions import DomainError
from app.shared.settings import settings
from app.quotes.application.notifications import send_quote_available
from app.quotes.domain.entities import Customer, Quote, QuoteItem
from app.quotes.domain.ports import AlreadyProcessedError, IQuoteRepository
from app.quotes.domain.value_objects import QuoteStatus

logger = logging.getLogger(__name__)


def _reply(command: Envelope, event_type: str, payload: dict) -> Envelope:
    return Envelope(type=event_type, payload=payload, saga_id=command.saga_id, order_id=command.order_id)


def quote_generated_payload(quote: Quote) -> dict:
    return {
        "quote_id": quote.quote_id,
        "labor_total": quote.labor_total,
        "parts_total": quote.parts_total,
        "total": quote.total,
        "valid_until": quote.valid_until.isoformat(),
    }


def _items(entries: list[dict], id_key: str) -> list[QuoteItem]:
    return [QuoteItem(str(e[id_key]), str(e["name"]), int(e["quantity"]), float(e["unit_price"])) for e in entries]


class GenerateQuoteUseCase:
    """`GerarOrcamento`: monta o orçamento com os itens do diagnóstico e envia
    o link de aprovação ao cliente."""

    def __init__(self, repo: IQuoteRepository, notifier: IEmailNotifier | None = None, public_base_url: str | None = None) -> None:
        self._repo = repo
        self._notifier = notifier or NullEmailNotifier()
        self._public_base_url = public_base_url or settings.public_base_url

    def execute(self, command: Envelope) -> None:
        if self._repo.is_processed(command.message_id):
            return
        try:
            quote = self._handle(command)
        except AlreadyProcessedError:
            logger.info("mensagem já processada message_id=%s", command.message_id)
            return
        if quote is not None:
            send_quote_available(self._notifier, quote, self._public_base_url)

    def _handle(self, command: Envelope) -> Quote | None:
        existing = self._repo.get_by_order(command.order_id) if command.order_id is not None else None
        if existing is not None:
            reply = (
                _reply(command, "OrcamentoGerado", quote_generated_payload(existing))
                if existing.saga_id == command.saga_id
                else _reply(command, "OrcamentoFalhou", {"reason": "os_ja_tem_orcamento"})
            )
            self._repo.reply([reply], command.message_id)
            return None

        if command.saga_id and self._repo.is_saga_compensated(command.saga_id):
            # CancelarOrcamento chegou antes (fila sem ordem garantida): criar o
            # orçamento agora mandaria ao cliente o link de uma OS já cancelada.
            self._repo.reply([_reply(command, "OrcamentoFalhou", {"reason": "saga_ja_compensada"})], command.message_id)
            return None

        try:
            quote = self._build(command)
        except (DomainError, KeyError, TypeError, ValueError) as error:
            logger.warning("GerarOrcamento inválido order_id=%s: %s", command.order_id, error)
            self._repo.reply([_reply(command, "OrcamentoFalhou", {"reason": "payload_invalido"})], command.message_id)
            return None

        self._repo.save(quote, expected_status=None, events=[_reply(command, "OrcamentoGerado", quote_generated_payload(quote))], message_id=command.message_id)
        return quote

    def _build(self, command: Envelope) -> Quote:
        if command.order_id is None or not command.saga_id:
            raise DomainError("Comando sem order_id ou saga_id.")
        payload = command.payload
        customer = payload.get("customer") or {}
        now = datetime.now(UTC)
        return Quote(
            order_id=command.order_id,
            saga_id=command.saga_id,
            quote_id=str(uuid.uuid4()),
            # 256 bits: é o que autoriza o cliente a aprovar sem login.
            token=secrets.token_urlsafe(32),
            customer=Customer(name=customer.get("name"), email=customer.get("email")),
            notes=str(payload.get("notes") or ""),
            services=_items(payload.get("services", []), "service_id"),
            parts=_items(payload.get("parts", []), "part_id"),
            status=QuoteStatus.AWAITING_APPROVAL,
            created_at=now,
            valid_until=now + timedelta(days=settings.quote_validity_days),
        )


class CancelQuoteUseCase:
    """`CancelarOrcamento` (compensação). Sempre confirma com
    `OrcamentoCancelado`, mesmo sem nada a cancelar."""

    def __init__(self, repo: IQuoteRepository) -> None:
        self._repo = repo

    def execute(self, command: Envelope) -> None:
        if self._repo.is_processed(command.message_id):
            return
        try:
            quote = self._repo.get_by_order(command.order_id) if command.order_id is not None else None
            reply = _reply(command, "OrcamentoCancelado", {"quote_id": quote.quote_id if quote else None})
            if quote is None:
                self._repo.reply([reply], command.message_id, compensated_saga_id=command.saga_id)
                return
            previous = quote.status
            if quote.cancel(datetime.now(UTC)):
                self._repo.save(quote, expected_status=previous, events=[reply], message_id=command.message_id)
            else:
                self._repo.reply([reply], command.message_id)
        except AlreadyProcessedError:
            logger.info("mensagem já processada message_id=%s", command.message_id)
