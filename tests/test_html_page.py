from fastapi.testclient import TestClient

from app.messaging.dispatcher import Dispatcher
from app.quotes.adapters.dynamodb_repository import DynamoDBQuoteRepository
from tests.conftest import FakeNotifier, generate, outbox


def test_customer_approves_through_html_page(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    generate(dispatcher, notes="<script>alert(1)</script>")
    token = repo.get_by_order(42).token
    assert f"https://oficina.test/orcamento/{token}" in notifier.sent[0].body

    page = client.get(f"/orcamento/{token}")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "R$ 355,50" in page.text and "Aprovar orçamento" in page.text
    assert "<script>alert(1)</script>" not in page.text  # dados escapados

    approved = client.post(f"/orcamento/{token}/aprovar")
    assert approved.status_code == 200
    assert "Sua aprovação foi registrada" in approved.text and "Aprovar orçamento" not in approved.text
    assert outbox()[-1]["type"] == "OrcamentoAprovado"

    again = client.post(f"/orcamento/{token}/recusar")
    assert again.status_code == 409 and "já está aprovado" in again.text


def test_reject_and_unknown_token(client: TestClient, dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    generate(dispatcher)
    token = repo.get_by_order(42).token
    assert "Sua recusa foi registrada" in client.post(f"/orcamento/{token}/recusar").text
    assert client.get("/orcamento/nao-existe").status_code == 404
