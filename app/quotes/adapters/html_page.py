"""Página HTML mínima do link de aprovação (o que o cliente vê ao clicar no
e-mail). Sem framework de templates: só f-strings com `html.escape` em todo
valor que vem de dados."""

from html import escape

from app.quotes.domain.entities import Quote, QuoteItem
from app.quotes.domain.value_objects import QuoteStatus

_STATUS_TEXT = {
    QuoteStatus.AWAITING_APPROVAL: "Aguardando a sua resposta",
    QuoteStatus.APPROVED: "Aprovado. Você receberá o link de pagamento por e-mail.",
    QuoteStatus.REJECTED: "Recusado. Entre em contato com a oficina se quiser revisar o orçamento.",
    QuoteStatus.CANCELLED: "Cancelado pela oficina.",
}


def _money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rows(items: list[QuoteItem]) -> str:
    return "".join(
        f"<tr><td>{escape(i.name)}</td><td class='n'>{i.quantity}</td><td class='n'>{_money(i.unit_price)}</td>"
        f"<td class='n'>{_money(i.subtotal)}</td></tr>"
        for i in items
    )


def render_quote_page(quote: Quote, token: str, message: str | None = None) -> str:
    actions = ""
    if quote.status == QuoteStatus.AWAITING_APPROVAL:
        base = f"/orcamento/{escape(token)}"
        actions = (
            f"<form method='post' action='{base}/aprovar'><button class='approve'>Aprovar orçamento</button></form>"
            f"<form method='post' action='{base}/recusar'><button class='reject'>Recusar</button></form>"
        )
    notice = f"<p class='notice'>{escape(message)}</p>" if message else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orçamento da OS #{quote.order_id}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 680px; margin: 2rem auto; padding: 0 1rem; color: #1f2933; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: .5rem; border-bottom: 1px solid #e4e7eb; text-align: left; }}
  .n {{ text-align: right; }}
  .total td {{ font-weight: 600; }}
  .status {{ padding: .75rem; background: #f5f7fa; border-radius: 6px; }}
  .notice {{ padding: .75rem; background: #fff8e1; border-radius: 6px; }}
  form {{ display: inline-block; margin-right: .5rem; }}
  button {{ font: inherit; font-size: 1rem; padding: .6rem 1.2rem; border: 0; border-radius: 6px; cursor: pointer; }}
  .approve {{ background: #2f855a; color: white; }}
  .reject {{ background: #e4e7eb; }}
</style>
</head>
<body>
<h1>Orçamento da OS #{quote.order_id}</h1>
{notice}
<p class="status"><strong>Situação:</strong> {escape(_STATUS_TEXT[quote.status])}</p>
<p><strong>Diagnóstico:</strong> {escape(quote.notes)}</p>
<table>
<thead><tr><th>Item</th><th class="n">Qtd.</th><th class="n">Preço unit.</th><th class="n">Subtotal</th></tr></thead>
<tbody>{_rows(quote.services)}{_rows(quote.parts)}</tbody>
<tfoot>
<tr><td colspan="3">Mão de obra</td><td class="n">{_money(quote.labor_total)}</td></tr>
<tr><td colspan="3">Peças</td><td class="n">{_money(quote.parts_total)}</td></tr>
<tr class="total"><td colspan="3">Total</td><td class="n">{_money(quote.total)}</td></tr>
</tfoot>
</table>
<p>Válido até {quote.valid_until.strftime("%d/%m/%Y")}.</p>
{actions}
</body>
</html>"""
