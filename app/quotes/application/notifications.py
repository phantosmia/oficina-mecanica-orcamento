import logging

from app.shared.email import IEmailNotifier, quote_available_message, quote_decision_message
from app.quotes.domain.entities import Quote

logger = logging.getLogger(__name__)


def approval_url(public_base_url: str, token: str) -> str:
    """Link enviado ao cliente: a página HTML com o orçamento e os botões de
    aprovar/recusar. A mesma decisão está disponível em JSON em `/public/quotes/{token}`."""
    return f"{public_base_url.rstrip('/')}/orcamento/{token}"


def send_quote_available(notifier: IEmailNotifier, quote: Quote, public_base_url: str) -> bool:
    """Envia o e-mail com o link de aprovação. É uma tentativa única, feita
    depois do commit: uma falha de e-mail não pode desfazer o orçamento nem
    travar a saga. O admin pode reenviar (`POST /quotes/{order_id}/resend-email`)
    ou pegar o link em `GET /quotes/{order_id}`. Retorna se houve envio."""
    if not quote.customer.email:
        logger.info("OS %s sem e-mail do cliente: orçamento não enviado por e-mail", quote.order_id)
        return False
    subject, body = quote_available_message(
        quote.order_id,
        quote.customer.name,
        quote.total,
        approval_url(public_base_url, quote.token),
        quote.valid_until.strftime("%d/%m/%Y"),
    )
    try:
        notifier.send(to=quote.customer.email, subject=subject, body=body)
    except Exception:
        logger.exception("falha ao enviar o orçamento da OS %s por e-mail", quote.order_id)
        return False
    return True


def send_decision(notifier: IEmailNotifier, quote: Quote, approved: bool) -> None:
    if not quote.customer.email:
        return
    subject, body = quote_decision_message(quote.order_id, approved)
    try:
        notifier.send(to=quote.customer.email, subject=subject, body=body)
    except Exception:
        logger.exception("falha ao enviar a confirmação da decisão da OS %s", quote.order_id)
