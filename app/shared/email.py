from abc import ABC, abstractmethod


class IEmailNotifier(ABC):
    """Port — define o contrato de envio de notificações por e-mail."""

    @abstractmethod
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class NullEmailNotifier(IEmailNotifier):
    """Implementação no-op usada em testes e quando SMTP está desabilitado."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        pass


# ── templates de mensagem ─────────────────────────────────────────────────────


def quote_available_message(order_id: int, customer_name: str | None, total: float, approval_url: str, valid_until: str) -> tuple[str, str]:
    subject = f"[OS #{order_id}] Orçamento disponível para aprovação"
    greeting = f"Olá, {customer_name}!" if customer_name else "Olá!"
    body = (
        f"{greeting}\n\n"
        f"O diagnóstico do seu veículo foi concluído e o orçamento da Ordem de Serviço #{order_id} está pronto.\n"
        f"Valor total: R$ {total:.2f}\n"
        f"Válido até: {valid_until}\n\n"
        f"Veja os itens e aprove ou recuse pelo link:\n"
        f"{approval_url}\n\n"
        f"Depois da aprovação, você receberá o link de pagamento.\n\n"
        f"Atenciosamente,\nOficina Mecânica FIAP"
    )
    return subject, body


def quote_decision_message(order_id: int, approved: bool) -> tuple[str, str]:
    if approved:
        subject = f"[OS #{order_id}] Orçamento aprovado"
        text = "Recebemos a aprovação do orçamento. Em instantes você receberá o link de pagamento."
    else:
        subject = f"[OS #{order_id}] Orçamento recusado"
        text = "Registramos a recusa do orçamento. Entre em contato conosco caso queira revisá-lo."
    body = f"Olá!\n\n{text}\n\nAtenciosamente,\nOficina Mecânica FIAP"
    return subject, body
