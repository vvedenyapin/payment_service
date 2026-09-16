import asyncio
import logging
import uuid
from decimal import Decimal

import httpx

from app.config import settings
from app.models.payment import PaymentStatus

logger = logging.getLogger(__name__)


async def send_webhook_with_retry(
    *,
    webhook_url: str,
    payment_id: uuid.UUID,
    status: PaymentStatus,
    amount: Decimal,
    currency: str,
) -> bool:
    """Отправляет клиенту webhook о результате обработки платежа.
    При ошибке доставки делает до settings.webhook_max_retries повторных попыток
    с экспоненциальной задержкой (1s, 2s, 4s, ...). Возвращает True, если хотя бы
    одна попытка была успешной (получен 2xx ответ)."""
    payload = {
        "payment_id": str(payment_id),
        "status": status.value,
        "amount": str(amount),
        "currency": currency,
    }

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        for attempt in range(1, settings.webhook_max_retries + 1):
            try:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                logger.info(
                    "Webhook delivered: payment_id=%s attempt=%s status_code=%s",
                    payment_id,
                    attempt,
                    response.status_code,
                )
                return True
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "Webhook delivery failed: payment_id=%s attempt=%s/%s error=%s",
                    payment_id,
                    attempt,
                    settings.webhook_max_retries,
                    exc,
                )
                if attempt < settings.webhook_max_retries:
                    backoff = settings.webhook_base_backoff_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

    logger.error(
        "Webhook permanently failed after %s attempts: payment_id=%s last_error=%s",
        settings.webhook_max_retries,
        payment_id,
        last_error,
    )
    return False
