from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.shared.dependencies import get_current_admin
from app.shared.dynamodb import get_table
from app.shared.email import IEmailNotifier
from app.shared.exceptions import DomainError, NotFoundError
from app.shared.http_errors import domain_error_handler
from app.shared.settings import settings
from app.shared.smtp_notifier import SmtpEmailNotifier
from app.quotes.adapters.dynamodb_repository import DynamoDBQuoteRepository
from app.quotes.adapters.html_page import render_quote_page
from app.quotes.adapters.presenter import to_admin_response, to_public_response
from app.quotes.application.use_cases import (
    DecideQuoteUseCase,
    GetQuoteByOrderUseCase,
    GetQuoteByTokenUseCase,
    ResendQuoteEmailUseCase,
)
from app.quotes.domain.ports import IQuoteRepository
from app.quotes.domain.value_objects import Decider
from app.quotes.schemas import PublicQuoteRead, QuoteRead, ResendResult


def get_repo() -> IQuoteRepository:
    return DynamoDBQuoteRepository(get_table())


def get_notifier() -> IEmailNotifier:
    return SmtpEmailNotifier()


# ── Cliente: link do e-mail, sem login. O token é a autorização. ─────────────

public_router = APIRouter(prefix="/public/quotes", tags=["public"])


@public_router.get("/{token}", response_model=PublicQuoteRead)
def view_quote(token: str, repo: IQuoteRepository = Depends(get_repo)) -> PublicQuoteRead:
    with domain_error_handler():
        return to_public_response(GetQuoteByTokenUseCase(repo).execute(token))


@public_router.post("/{token}/approve", response_model=PublicQuoteRead)
def approve_by_customer(token: str, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> PublicQuoteRead:
    with domain_error_handler():
        quote = GetQuoteByTokenUseCase(repo).execute(token)
        return to_public_response(DecideQuoteUseCase(repo, notifier).execute(quote, approve=True, by=Decider.CUSTOMER))


@public_router.post("/{token}/reject", response_model=PublicQuoteRead)
def reject_by_customer(token: str, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> PublicQuoteRead:
    with domain_error_handler():
        quote = GetQuoteByTokenUseCase(repo).execute(token)
        return to_public_response(DecideQuoteUseCase(repo, notifier).execute(quote, approve=False, by=Decider.CUSTOMER))


# ── Página HTML do link (o que o cliente abre a partir do e-mail) ────────────

page_router = APIRouter(prefix="/orcamento", tags=["public"], include_in_schema=False)


def _page_quote(repo: IQuoteRepository, token: str):  # noqa: ANN202
    try:
        return GetQuoteByTokenUseCase(repo).execute(token)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.") from error


@page_router.get("/{token}", response_class=HTMLResponse)
def quote_page(token: str, repo: IQuoteRepository = Depends(get_repo)) -> HTMLResponse:
    return HTMLResponse(render_quote_page(_page_quote(repo, token), token))


def _decide_from_page(token: str, approve: bool, repo: IQuoteRepository, notifier: IEmailNotifier) -> HTMLResponse:
    quote = _page_quote(repo, token)
    try:
        quote = DecideQuoteUseCase(repo, notifier).execute(quote, approve=approve, by=Decider.CUSTOMER)
        message = "Obrigado! Sua aprovação foi registrada." if approve else "Sua recusa foi registrada."
        status_code = 200
    except DomainError as error:
        quote = _page_quote(repo, token)
        message, status_code = str(error), 409
    return HTMLResponse(render_quote_page(quote, token, message), status_code=status_code)


@page_router.post("/{token}/aprovar", response_class=HTMLResponse)
def approve_from_page(token: str, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> HTMLResponse:
    return _decide_from_page(token, True, repo, notifier)


@page_router.post("/{token}/recusar", response_class=HTMLResponse)
def reject_from_page(token: str, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> HTMLResponse:
    return _decide_from_page(token, False, repo, notifier)


# ── Admin (JWT do OS Service) ────────────────────────────────────────────────

admin_router = APIRouter(prefix="/quotes", tags=["quotes"], dependencies=[Depends(get_current_admin)])


@admin_router.get("/{order_id}", response_model=QuoteRead)
def get_quote(order_id: int, repo: IQuoteRepository = Depends(get_repo)) -> QuoteRead:
    """Orçamento da OS, incluindo o link de aprovação enviado ao cliente."""
    with domain_error_handler():
        return to_admin_response(GetQuoteByOrderUseCase(repo).execute(order_id), settings.public_base_url)


@admin_router.post("/{order_id}/approve", response_model=QuoteRead)
def approve_by_admin(order_id: int, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> QuoteRead:
    """Aprovação em nome do cliente (ex.: por telefone)."""
    with domain_error_handler():
        quote = GetQuoteByOrderUseCase(repo).execute(order_id)
        return to_admin_response(DecideQuoteUseCase(repo, notifier).execute(quote, approve=True, by=Decider.ADMIN), settings.public_base_url)


@admin_router.post("/{order_id}/reject", response_model=QuoteRead)
def reject_by_admin(order_id: int, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> QuoteRead:
    with domain_error_handler():
        quote = GetQuoteByOrderUseCase(repo).execute(order_id)
        return to_admin_response(DecideQuoteUseCase(repo, notifier).execute(quote, approve=False, by=Decider.ADMIN), settings.public_base_url)


@admin_router.post("/{order_id}/resend-email", response_model=ResendResult)
def resend_email(order_id: int, repo: IQuoteRepository = Depends(get_repo), notifier: IEmailNotifier = Depends(get_notifier)) -> ResendResult:
    with domain_error_handler():
        return ResendResult(sent=ResendQuoteEmailUseCase(repo, notifier, settings.public_base_url).execute(order_id))
