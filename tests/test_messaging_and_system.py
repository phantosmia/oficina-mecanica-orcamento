import json

import boto3
from fastapi.testclient import TestClient

from app.messaging.dispatcher import Dispatcher, parse_body
from app.messaging.sqs_consumer import SqsConsumer
from app.shared.dynamodb import get_table
from app.shared.outbox import OutboxRelay
from app.shared.settings import settings
from app.shared.smtp_notifier import SmtpEmailNotifier
from app.shared.sns_publisher import SnsEventPublisher
from tests.conftest import command_msg, diagnosis_payload


def test_command_round_trip(dispatcher: Dispatcher) -> None:
    sqs, sns = boto3.client("sqs", region_name="us-east-1"), boto3.client("sns", region_name="us-east-1")
    orchestrator = sqs.create_queue(QueueName="os-saga-eventos")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=orchestrator, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=settings.events_topic_arn, Protocol="sqs", Endpoint=arn, Attributes={"RawMessageDelivery": "true"})

    command = command_msg("GerarOrcamento", order_id=7, saga_id="saga-7", **diagnosis_payload())
    sqs.send_message(QueueUrl=settings.commands_queue_url, MessageBody=json.dumps(command.to_dict()))

    assert SqsConsumer([settings.commands_queue_url], dispatcher, wait_seconds=0).poll_once() == 1
    assert OutboxRelay(get_table(), SnsEventPublisher(settings.events_topic_arn)).run_once() == 1
    [received] = sqs.receive_message(QueueUrl=orchestrator, MessageAttributeNames=["All"])["Messages"]
    assert json.loads(received["Body"])["type"] == "OrcamentoGerado"
    assert received["MessageAttributes"]["saga_id"]["StringValue"] == "saga-7"


def test_parse_body_unwraps_sns_notification() -> None:
    inner = command_msg("CancelarOrcamento").to_dict()
    assert parse_body(json.dumps({"Type": "Notification", "Message": json.dumps(inner)})).to_dict() == inner


def test_smtp_disabled_sends_nothing() -> None:
    SmtpEmailNotifier().send(to="maria@example.com", subject="x", body="y")  # SMTP_ENABLED=false: não tenta conectar


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["table_status"] == "ACTIVE"
    boto3.client("dynamodb", region_name="us-east-1").delete_table(TableName=settings.table_name)
    assert client.get("/ready").status_code == 503
