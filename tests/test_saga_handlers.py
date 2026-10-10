from app.messaging.dispatcher import Dispatcher
from app.quotes.adapters.dynamodb_repository import DynamoDBQuoteRepository
from app.quotes.domain.value_objects import QuoteStatus
from tests.conftest import FakeNotifier, command_msg, diagnosis_payload, generate, outbox


def test_generate_quote_from_diagnosis(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    command = generate(dispatcher)

    quote = repo.get_by_order(42)
    assert quote.status == QuoteStatus.AWAITING_APPROVAL
    assert [(i.item_id, i.quantity) for i in quote.parts] == [("part-oleo", 4), ("part-filtro", 1)]
    [reply] = outbox()
    assert (reply["type"], reply["saga_id"], reply["order_id"]) == ("OrcamentoGerado", command.saga_id, 42)
    assert reply["payload"] | {"valid_until": None} == {
        "quote_id": quote.quote_id, "labor_total": 150.0, "parts_total": 205.5, "total": 355.5, "valid_until": None,
    }
    [email] = notifier.sent
    assert email.to == "maria@example.com"
    assert "R$ 355.50" in email.body
    assert f"https://oficina.test/orcamento/{quote.token}" in email.body


def test_totals_are_recalculated_not_trusted(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    generate(dispatcher, total=1.0, labor_total=1.0, parts_total=0.0)
    assert repo.get_by_order(42).total == 355.5


def test_no_email_without_customer_email(dispatcher: Dispatcher, notifier: FakeNotifier) -> None:
    generate(dispatcher, customer={"name": "Sem e-mail"})
    assert notifier.sent == []
    assert outbox()[0]["type"] == "OrcamentoGerado"


def test_email_failure_does_not_break_the_saga(repo: DynamoDBQuoteRepository) -> None:
    class Broken(FakeNotifier):
        def send(self, **kwargs):  # noqa: ANN003, ANN201
            raise ConnectionError("SMTP fora do ar")

    generate(Dispatcher(lambda: repo, Broken()))
    assert repo.get_by_order(42) is not None
    assert outbox()[0]["type"] == "OrcamentoGerado"


def test_redelivery_and_resend(dispatcher: Dispatcher, notifier: FakeNotifier) -> None:
    command = generate(dispatcher)
    dispatcher.handle(command)  # reentrega: nada
    generate(dispatcher)  # reenvio (novo message_id): responde de novo, sem novo e-mail

    assert [m["type"] for m in outbox()] == ["OrcamentoGerado", "OrcamentoGerado"]
    assert outbox()[0]["payload"]["quote_id"] == outbox()[1]["payload"]["quote_id"]
    assert len(notifier.sent) == 1


def test_other_saga_for_same_order_fails(dispatcher: Dispatcher) -> None:
    generate(dispatcher)
    generate(dispatcher, saga_id="outra")
    assert outbox()[-1]["type"] == "OrcamentoFalhou"
    assert outbox()[-1]["payload"] == {"reason": "os_ja_tem_orcamento"}


def test_invalid_payload_fails(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    dispatcher.handle(command_msg("GerarOrcamento", **diagnosis_payload(services=[], parts=[])))
    dispatcher.handle(command_msg("GerarOrcamento", order_id=43, saga_id="s43", services=[{"service_id": "x"}]))
    assert [m["payload"] for m in outbox()] == [{"reason": "payload_invalido"}, {"reason": "payload_invalido"}]
    assert repo.get_by_order(42) is None


def test_cancel_awaiting_and_approved_quotes(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    generate(dispatcher)
    dispatcher.handle(command_msg("CancelarOrcamento"))
    dispatcher.handle(command_msg("CancelarOrcamento"))  # compensação repetida: confirma de novo

    assert repo.get_by_order(42).status == QuoteStatus.CANCELLED
    replies = [m for m in outbox() if m["type"] == "OrcamentoCancelado"]
    assert len(replies) == 2 and replies[0]["payload"]["quote_id"] == repo.get_by_order(42).quote_id


def test_cancel_keeps_rejected_status(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository) -> None:
    from app.quotes.application.use_cases import DecideQuoteUseCase
    from app.quotes.domain.value_objects import Decider

    generate(dispatcher)
    DecideQuoteUseCase(repo).execute(repo.get_by_order(42), approve=False, by=Decider.CUSTOMER)
    dispatcher.handle(command_msg("CancelarOrcamento"))

    assert repo.get_by_order(42).status == QuoteStatus.REJECTED
    assert outbox()[-1]["type"] == "OrcamentoCancelado"


def test_cancel_before_generate_blocks_late_quote(dispatcher: Dispatcher, repo: DynamoDBQuoteRepository, notifier: FakeNotifier) -> None:
    """Fora de ordem: o cliente nunca pode receber o link de uma OS já cancelada."""
    dispatcher.handle(command_msg("CancelarOrcamento"))
    generate(dispatcher)

    assert repo.get_by_order(42) is None
    assert notifier.sent == []
    assert [(m["type"], m["payload"].get("reason")) for m in outbox()] == [
        ("OrcamentoCancelado", None), ("OrcamentoFalhou", "saga_ja_compensada"),
    ]


def test_unknown_type(dispatcher: Dispatcher) -> None:
    assert dispatcher.handle(command_msg("Desconhecido")) is False
