from enum import StrEnum


class QuoteStatus(StrEnum):
    AWAITING_APPROVAL = "aguardando_aprovacao"
    APPROVED = "aprovado"
    REJECTED = "recusado"
    CANCELLED = "cancelado"   # compensação da saga (prazo expirado, falha no pagamento etc.)


class Decider(StrEnum):
    """Quem aprovou ou recusou."""

    CUSTOMER = "cliente"      # pelo link do e-mail
    ADMIN = "admin"           # pela API, em nome do cliente (ex.: aprovação por telefone)
