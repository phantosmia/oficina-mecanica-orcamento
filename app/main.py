from fastapi import FastAPI

from app.quotes.controller import admin_router, page_router, public_router
from app.shared.logging_config import RequestIDMiddleware, configure_logging
from app.shared.settings import settings
from app.system.controller import router as system_router

configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    description=(
        "Microsserviço de Orçamento da oficina mecânica: gera o orçamento a partir do diagnóstico e registra a "
        "aprovação ou recusa do cliente. As rotas /public/quotes/{token} são o link enviado ao cliente (o token "
        "é a autorização); as rotas /quotes exigem o JWT de admin emitido pelo OS Service."
    ),
    version="1.0.0",
)

app.add_middleware(RequestIDMiddleware)

app.include_router(system_router)
app.include_router(public_router)
app.include_router(page_router)
app.include_router(admin_router)
