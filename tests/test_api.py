from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.messaging.dispatcher import Dispatcher
from app.quotes.adapters.dynamodb_repository import DynamoDBQuoteRepository
from app.quotes.domain.value_objects import QuoteStatus
from app.shared.exceptions import ConcurrencyError
from tests.conftest import FakeNotifier, generate, make_token, outbox


def token_of(repo: DynamoDBQuoteRepository, order_id: int = 42) -> str:
    return repo.get_by_order(order_id).token


def test_customer_views_quote_by_link_without_internal_data(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    generate(dispatcher)

    body = client.get(f"/public/quotes/{token_of(repo)}").json()

    assert (body["order_id"], body["status"], body["total"]) == (42, "aguardando_aprovacao", 355.5)
    assert [(i["name"], i["subtotal"]) for i in body["parts"]] == [("Óleo 5W30", 180.0), ("Filtro de óleo", 25.5)]
    assert not {"token", "saga_id", "customer_email", "approval_url", "quote_id"} & set(body)


def test_customer_approves_once(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    generate(dispatcher)
    token = token_of(repo)

    approved = client.post(f"/public/quotes/{token}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "aprovado"
    assert client.post(f"/public/quotes/{token}/reject").status_code == 409
    assert client.post(f"/public/quotes/{token}/approve").status_code == 409

    decision = outbox()[-1]
    assert (decision["type"], decision["saga_id"], decision["order_id"]) == ("OrcamentoAprovado", "saga-42", 42)
    assert decision["payload"] == {"quote_id": repo.get_by_order(42).quote_id, "total": 355.5, "decided_by": "cliente"}
    assert notifier.sent[-1].subject == "[OS #42] Orçamento aprovado"


def test_customer_rejects(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    generate(dispatcher)
    assert client.post(f"/public/quotes/{token_of(repo)}/reject").json()["status"] == "recusado"
    assert outbox()[-1]["type"] == "OrcamentoRecusado"


def test_unknown_token_is_404(client: TestClient, notifier: FakeNotifier) -> None:
    assert client.get("/public/quotes/nao-existe").status_code == 404
    assert client.post("/public/quotes/nao-existe/approve").status_code == 404


def test_expired_quote_cannot_be_approved(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    generate(dispatcher)
    quote = repo.get_by_order(42)
    quote.valid_until = datetime.now(UTC) - timedelta(minutes=1)
    repo.save(quote, expected_status=QuoteStatus.AWAITING_APPROVAL, events=[])

    response = client.post(f"/public/quotes/{quote.token}/approve")
    assert response.status_code == 409 and "expirou" in response.json()["detail"]


def test_cancelled_quote_link_shows_status_and_refuses_decision(
    client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier
) -> None:
    from tests.conftest import command_msg

    generate(dispatcher)
    dispatcher.handle(command_msg("CancelarOrcamento"))
    token = token_of(repo)
    assert client.get(f"/public/quotes/{token}").json()["status"] == "cancelado"
    assert client.post(f"/public/quotes/{token}/approve").status_code == 409


ADMIN_ROUTES = [("get", "/quotes/42"), ("post", "/quotes/42/approve"), ("post", "/quotes/42/reject"), ("post", "/quotes/42/resend-email")]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_admin_routes_require_admin(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"Authorization": f"Bearer {make_token('12345678909')}"}).status_code == 401


def test_admin_sees_approval_link_and_approves_for_customer(
    client: TestClient, admin_headers: dict[str, str], dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier
) -> None:
    generate(dispatcher)

    quote = client.get("/quotes/42", headers=admin_headers).json()
    assert quote["approval_url"] == f"https://oficina.test/orcamento/{token_of(repo)}"
    assert (quote["customer_email"], quote["saga_id"]) == ("maria@example.com", "saga-42")

    approved = client.post("/quotes/42/approve", headers=admin_headers).json()
    assert (approved["status"], approved["decided_by"]) == ("aprovado", "admin")
    assert outbox()[-1]["payload"]["decided_by"] == "admin"


def test_admin_rejects_for_customer(client: TestClient, admin_headers: dict[str, str], dispatcher: Dispatcher, notifier: FakeNotifier) -> None:
    generate(dispatcher)
    assert client.post("/quotes/42/reject", headers=admin_headers).json()["status"] == "recusado"


def test_resend_email(client: TestClient, admin_headers: dict[str, str], dispatcher: Dispatcher, notifier: FakeNotifier) -> None:
    generate(dispatcher)
    assert client.post("/quotes/42/resend-email", headers=admin_headers).json() == {"sent": True}
    assert len(notifier.sent) == 2

    client.post("/quotes/42/approve", headers=admin_headers)
    assert client.post("/quotes/42/resend-email", headers=admin_headers).status_code == 409


def test_admin_not_found(client: TestClient, admin_headers: dict[str, str], notifier: FakeNotifier) -> None:
    for method, path in ADMIN_ROUTES:
        assert getattr(client, method)(path.replace("42", "999"), headers=admin_headers).status_code == 404


def test_simultaneous_approve_and_reject(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    """Cliente aprova pelo link enquanto o admin recusa: só uma decisão vale."""
    from app.quotes.application.use_cases import DecideQuoteUseCase
    from app.quotes.domain.value_objects import Decider

    generate(dispatcher)
    seen_by_admin = repo.get_by_order(42)
    DecideQuoteUseCase(repo).execute(repo.get_by_order(42), approve=True, by=Decider.CUSTOMER)

    with pytest.raises(ConcurrencyError):
        DecideQuoteUseCase(repo).execute(seen_by_admin, approve=False, by=Decider.ADMIN)
    assert repo.get_by_order(42).status == QuoteStatus.APPROVED
    assert [m["type"] for m in outbox()].count("OrcamentoRecusado") == 0
