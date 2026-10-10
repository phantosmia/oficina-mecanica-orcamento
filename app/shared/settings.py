from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str
    log_level: str
    # JWT de admin: emitido pelo OS Service; este serviço só valida.
    jwt_secret_key: str
    jwt_algorithm: str
    admin_username: str
    # AWS (localmente, AWS_ENDPOINT_URL aponta pro LocalStack)
    aws_region: str
    table_name: str
    events_topic_arn: str
    commands_queue_url: str
    worker_wait_seconds: int
    outbox_poll_interval_seconds: float
    # Orçamento
    public_base_url: str          # base do link de aprovação enviado ao cliente
    quote_validity_days: int      # prazo exibido no orçamento e aplicado na aprovação
    # SMTP / e-mail (mesmas variáveis do OS Service)
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_from: str
    smtp_username: str
    smtp_password: str


settings = Settings(
    app_name="Oficina Mecânica — Orçamento",
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    jwt_secret_key=os.getenv("JWT_SECRET_KEY", "change-me-in-production"),
    jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    admin_username=os.getenv("ADMIN_USERNAME", "admin"),
    aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
    table_name=os.getenv("ORCAMENTO_TABLE_NAME", "oficina-orcamento"),
    events_topic_arn=os.getenv("ORCAMENTO_EVENTS_TOPIC_ARN", ""),
    commands_queue_url=os.getenv("ORCAMENTO_COMMANDS_QUEUE_URL", ""),
    worker_wait_seconds=int(os.getenv("WORKER_WAIT_SECONDS", "10")),
    outbox_poll_interval_seconds=float(os.getenv("OUTBOX_POLL_INTERVAL_SECONDS", "2")),
    public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8004"),
    quote_validity_days=int(os.getenv("QUOTE_VALIDITY_DAYS", "7")),
    smtp_enabled=os.getenv("SMTP_ENABLED", "false").lower() == "true",
    smtp_host=os.getenv("SMTP_HOST", "localhost"),
    smtp_port=int(os.getenv("SMTP_PORT", "587")),
    smtp_from=os.getenv("SMTP_FROM", "noreply@oficina.local"),
    smtp_username=os.getenv("SMTP_USERNAME", ""),
    smtp_password=os.getenv("SMTP_PASSWORD", ""),
)
