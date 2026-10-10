from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError

from app.shared.dynamodb import query_gsi1, to_dynamo_number
from app.shared.events import Envelope
from app.shared.exceptions import ConcurrencyError
from app.shared.outbox import outbox_put
from app.quotes.domain.entities import Customer, Quote, QuoteItem
from app.quotes.domain.ports import AlreadyProcessedError, IQuoteRepository
from app.quotes.domain.value_objects import Decider, QuoteStatus


def _pk(order_id: int) -> str:
    return f"QUOTE#{order_id}"


def _items_to_dynamo(items: list[QuoteItem]) -> list[dict[str, Any]]:
    return [{"id": i.item_id, "name": i.name, "quantity": i.quantity, "unit_price": to_dynamo_number(i.unit_price)} for i in items]


def _items_from_dynamo(items: list[dict[str, Any]]) -> list[QuoteItem]:
    return [QuoteItem(i["id"], i["name"], int(i["quantity"]), float(i["unit_price"])) for i in items]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _to_item(quote: Quote) -> dict[str, Any]:
    return {
        "pk": _pk(quote.order_id),
        # GSI1: o cliente chega pelo token do link, sem login.
        "gsi1pk": f"TOKEN#{quote.token}",
        "gsi1sk": "QUOTE",
        "order_id": quote.order_id,
        "saga_id": quote.saga_id,
        "quote_id": quote.quote_id,
        "token": quote.token,
        "customer": {"name": quote.customer.name, "email": quote.customer.email},
        "notes": quote.notes,
        "services": _items_to_dynamo(quote.services),
        "parts": _items_to_dynamo(quote.parts),
        # Totais gravados só para leitura/consulta; a fonte da verdade são os itens.
        "total": to_dynamo_number(quote.total),
        "status": quote.status.value,
        "created_at": _iso(quote.created_at),
        "valid_until": _iso(quote.valid_until),
        "decided_at": _iso(quote.decided_at),
        "decided_by": quote.decided_by.value if quote.decided_by else None,
        "cancelled_at": _iso(quote.cancelled_at),
    }


def _to_entity(item: dict[str, Any]) -> Quote:
    customer = item.get("customer") or {}
    return Quote(
        order_id=int(item["order_id"]),
        saga_id=item["saga_id"],
        quote_id=item["quote_id"],
        token=item["token"],
        customer=Customer(name=customer.get("name"), email=customer.get("email")),
        notes=item.get("notes") or "",
        services=_items_from_dynamo(item["services"]),
        parts=_items_from_dynamo(item["parts"]),
        status=QuoteStatus(item["status"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        valid_until=datetime.fromisoformat(item["valid_until"]),
        decided_at=_dt(item.get("decided_at")),
        decided_by=Decider(item["decided_by"]) if item.get("decided_by") else None,
        cancelled_at=_dt(item.get("cancelled_at")),
    )


def _cancellation_codes(error: ClientError) -> list[str]:
    return [reason.get("Code", "None") for reason in error.response.get("CancellationReasons", [])]


class DynamoDBQuoteRepository(IQuoteRepository):
    def __init__(self, table: Any) -> None:
        self._table = table
        self._client = table.meta.client

    def get_by_order(self, order_id: int) -> Quote | None:
        item = self._table.get_item(Key={"pk": _pk(order_id)}).get("Item")
        return _to_entity(item) if item else None

    def get_by_token(self, token: str) -> Quote | None:
        items = query_gsi1(self._table, f"TOKEN#{token}") if token else []
        # O GSI é eventualmente consistente e não garante unicidade: só aceita
        # exatamente um resultado (com 256 bits de token, dois é um bug).
        return _to_entity(items[0]) if len(items) == 1 else None

    def is_processed(self, message_id: str) -> bool:
        return "Item" in self._table.get_item(Key={"pk": f"MSG#{message_id}"})

    def save(self, quote: Quote, expected_status: QuoteStatus | None, events: list[Envelope], message_id: str | None = None) -> None:
        put: dict[str, Any] = {"TableName": self._table.name, "Item": _to_item(quote)}
        if expected_status is None:
            put["ConditionExpression"] = "attribute_not_exists(pk)"
        else:
            put["ConditionExpression"] = "#status = :expected"
            put["ExpressionAttributeNames"] = {"#status": "status"}
            put["ExpressionAttributeValues"] = {":expected": expected_status.value}
        self._transact([{"Put": put}], events, message_id)

    def reply(self, events: list[Envelope], message_id: str, compensated_saga_id: str | None = None) -> None:
        operations = (
            [{"Put": {"TableName": self._table.name, "Item": {"pk": f"COMPENSATED#{compensated_saga_id}"}}}]
            if compensated_saga_id
            else []
        )
        self._transact(operations, events, message_id)

    def is_saga_compensated(self, saga_id: str) -> bool:
        return "Item" in self._table.get_item(Key={"pk": f"COMPENSATED#{saga_id}"})

    def _transact(self, operations: list[dict[str, Any]], events: list[Envelope], message_id: str | None) -> None:
        items = list(operations)
        if message_id is not None:
            items.append(
                {"Put": {"TableName": self._table.name, "Item": {"pk": f"MSG#{message_id}"}, "ConditionExpression": "attribute_not_exists(pk)"}}
            )
        items.extend(outbox_put(self._table.name, event) for event in events)
        try:
            self._client.transact_write_items(TransactItems=items)
        except ClientError as error:
            codes = _cancellation_codes(error)

            def failed(index: int) -> bool:
                return index < len(codes) and codes[index] == "ConditionalCheckFailed"

            if message_id is not None and failed(len(operations)):
                raise AlreadyProcessedError(message_id) from error
            if operations and "ConditionExpression" in operations[0]["Put"] and failed(0):
                raise ConcurrencyError("O orçamento foi alterado por outra operação. Recarregue e tente de novo.") from error
            raise
