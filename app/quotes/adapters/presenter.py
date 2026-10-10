from app.quotes.application.notifications import approval_url
from app.quotes.domain.entities import Quote, QuoteItem
from app.quotes.schemas import PublicQuoteRead, QuoteItemRead, QuoteRead


def _item(item: QuoteItem) -> QuoteItemRead:
    return QuoteItemRead(id=item.item_id, name=item.name, quantity=item.quantity, unit_price=item.unit_price, subtotal=item.subtotal)


def _public_fields(quote: Quote) -> dict:
    return {
        "order_id": quote.order_id,
        "status": quote.status,
        "notes": quote.notes,
        "services": [_item(i) for i in quote.services],
        "parts": [_item(i) for i in quote.parts],
        "labor_total": quote.labor_total,
        "parts_total": quote.parts_total,
        "total": quote.total,
        "valid_until": quote.valid_until,
        "decided_at": quote.decided_at,
    }


def to_public_response(quote: Quote) -> PublicQuoteRead:
    return PublicQuoteRead(**_public_fields(quote))


def to_admin_response(quote: Quote, public_base_url: str) -> QuoteRead:
    return QuoteRead(
        **_public_fields(quote),
        quote_id=quote.quote_id,
        saga_id=quote.saga_id,
        customer_name=quote.customer.name,
        customer_email=quote.customer.email,
        approval_url=approval_url(public_base_url, quote.token),
        created_at=quote.created_at,
        decided_by=quote.decided_by,
        cancelled_at=quote.cancelled_at,
    )
