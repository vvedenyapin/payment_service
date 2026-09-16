import logging
import uuid
from decimal import Decimal
from typing import Any

from faststream.rabbit import RabbitMessage

from app.broker.broker import (
    broker,
    dlx_exchange,
    payments_exchange,
    payments_new_dlq,
    payments_new_queue,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.payment import PaymentStatus
from app.repositories.payment_repo import PaymentRepository
from app.services.gateway import emulate_payment_processing
from app.services.webhook import send_webhook_with_retry

logger = logging.getLogger(__name__)

RETRY_HEADER = "x-retry-count"


@broker.subscriber(payments_new_queue, payments_exchange)
async def handle_new_payment(body: dict[str, Any], message: RabbitMessage) -> None:
    """Единственный consumer, который делает всё:
    получает сообщение -> эмулирует обработку -> обновляет статус в БД ->
    шлёт webhook (с ретраями). При необработанном исключении сообщение не
    "падает" в requeue от RabbitMQ, а вручную переотправляется с увеличенным
    счётчиком попыток (x-retry-count), а после исчерпания MESSAGE_MAX_RETRIES
    попыток публикуется в Dead Letter Queue."""
    payment_id = body.get("payment_id")
    retry_count = int(message.headers.get(RETRY_HEADER, 0))

    logger.info("Processing payment %s (attempt %s)", payment_id, retry_count + 1)

    try:
        await _process_payment(body)
    except Exception as exc:  # noqa: BLE001 - обрабатываем любую ошибку обработки сообщения
        logger.exception("Error while processing payment %s: %s", payment_id, exc)
        await _handle_processing_failure(body, retry_count)


async def _process_payment(body: dict[str, Any]) -> None:
    payment_id = uuid.UUID(body["payment_id"])
    webhook_url = body["webhook_url"]
    amount = Decimal(body["amount"])
    currency = body["currency"]

    async with AsyncSessionLocal() as session:
        repo = PaymentRepository(session)
        payment = await repo.get_by_id(payment_id)

        if payment is None:
            logger.warning("Payment %s not found in DB, skipping message", payment_id)
            return

        if payment.status != PaymentStatus.PENDING:
            # Идемпотентность: если платёж уже обработан (например, сообщение
            # было доставлено повторно), просто выходим без побочных эффектов.
            logger.info(
                "Payment %s already processed (status=%s), skipping",
                payment_id,
                payment.status,
            )
            return

        result_status = await emulate_payment_processing()
        payment = await repo.update_status(payment_id, result_status)

    delivered = await send_webhook_with_retry(
        webhook_url=webhook_url,
        payment_id=payment_id,
        status=result_status,
        amount=amount,
        currency=currency,
    )
    if not delivered:
        logger.error(
            "Webhook for payment %s could not be delivered after %s attempts",
            payment_id,
            settings.webhook_max_retries,
        )


async def _handle_processing_failure(body: dict[str, Any], retry_count: int) -> None:
    payment_id = body.get("payment_id")
    next_attempt_number = retry_count + 1  # число уже совершённых попыток

    if next_attempt_number < settings.message_max_retries:
        logger.warning(
            "Re-publishing payment %s message for retry %s/%s",
            payment_id,
            next_attempt_number + 1,
            settings.message_max_retries,
        )
        await broker.publish(
            body,
            exchange=payments_exchange,
            routing_key=payments_new_queue.routing_key,
            headers={RETRY_HEADER: next_attempt_number},
        )
    else:
        logger.error(
            "Payment %s message exceeded max retries (%s), routing to DLQ",
            payment_id,
            settings.message_max_retries,
        )
        await broker.publish(
            body,
            exchange=dlx_exchange,
            routing_key=payments_new_dlq.routing_key,
            headers={RETRY_HEADER: next_attempt_number},
        )
