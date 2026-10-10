import os

_ACCOUNT = "123456789012"
os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "ORCAMENTO_TABLE_NAME": "oficina-orcamento-test",
        "ORCAMENTO_EVENTS_TOPIC_ARN": f"arn:aws:sns:us-east-1:{_ACCOUNT}:orcamento-eventos",
        "ORCAMENTO_COMMANDS_QUEUE_URL": f"https://sqs.us-east-1.amazonaws.com/{_ACCOUNT}/orcamento-comandos",
        "WORKER_WAIT_SECONDS": "0",
        "JWT_SECRET_KEY": "test-secret-key",
        "ADMIN_USERNAME": "admin",
        "PUBLIC_BASE_URL": "https://oficina.test",
        "QUOTE_VALIDITY_DAYS": "7",
        "SMTP_ENABLED": "false",
    }
)
os.environ.pop("AWS_ENDPOINT_URL", None)

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from moto import mock_aws

from app.main import app
from app.messaging.dispatcher import Dispatcher
from app.quotes.adapters.dynamodb_repository import DynamoDBQuoteRepository
from app.quotes.controller import get_notifier
from app.shared.dynamodb import get_table, query_gsi1
from app.shared.email import IEmailNotifier
from app.shared.events import Envelope
from app.shared.outbox import OUTBOX_PARTITION


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str


class FakeNotifier(IEmailNotifier):
    def __init__(self) -> None:
        self.sent: list[SentEmail] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append(SentEmail(to, subject, body))


@pytest.fixture(autouse=True)
def aws() -> Iterator[None]:
    with mock_aws():
        from scripts.bootstrap_local import bootstrap

        bootstrap()
        yield


@pytest.fixture
def repo(aws: None) -> DynamoDBQuoteRepository:
    return DynamoDBQuoteRepository(get_table())


@pytest.fixture
def notifier() -> Iterator[FakeNotifier]:
    fake = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_notifier, None)


@pytest.fixture
def dispatcher(notifier: FakeNotifier) -> Dispatcher:
    return Dispatcher(lambda: DynamoDBQuoteRepository(get_table()), notifier)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def make_token(subject: str = "admin") -> str:
    return jwt.encode({"sub": subject, "exp": datetime.now(UTC) + timedelta(minutes=5)}, "test-secret-key", algorithm="HS256")


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def command_msg(message_type: str, order_id: int = 42, saga_id: str = "saga-42", **payload: Any) -> Envelope:
    return Envelope(type=message_type, payload=dict(payload), saga_id=saga_id, order_id=order_id)


def diagnosis_payload(**overrides: Any) -> dict[str, Any]:
    """Payload de GerarOrcamento: o DiagnosticoConcluido da Execução + dados do cliente."""
    payload: dict[str, Any] = {
        "customer": {"name": "Maria", "email": "maria@example.com"},
        "notes": "Óleo vencido e filtro saturado",
        "services": [{"service_id": "svc-oleo", "name": "Troca de óleo", "quantity": 1, "unit_price": 150.0, "subtotal": 150.0}],
        "parts": [
            {"part_id": "part-oleo", "name": "Óleo 5W30", "quantity": 4, "unit_price": 45.0, "subtotal": 180.0},
            {"part_id": "part-filtro", "name": "Filtro de óleo", "quantity": 1, "unit_price": 25.5, "subtotal": 25.5},
        ],
        "labor_total": 150.0,
        "parts_total": 205.5,
        "total": 355.5,
    }
    payload.update(overrides)
    return payload


def generate(dispatcher: Dispatcher, order_id: int = 42, saga_id: str | None = None, **overrides: Any) -> Envelope:
    command = command_msg("GerarOrcamento", order_id=order_id, saga_id=saga_id or f"saga-{order_id}", **diagnosis_payload(**overrides))
    dispatcher.handle(command)
    return command


def outbox() -> list[dict]:
    return [json.loads(i["envelope"]) for i in query_gsi1(get_table(), OUTBOX_PARTITION)]
