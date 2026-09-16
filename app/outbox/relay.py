import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.broker.broker import broker, payments_exchange
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.outbox import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)

# Сопоставление exchange-имени из записи outbox на реальный RabbitExchange-объект,
# который FastStream должен объявить перед публикацией.
_EXCHANGES = {
    payments_exchange.name: payments_exchange,
}


async def _fetch_pending_batch(session, batch_size: int) -> list[OutboxEvent]:
    """Забирает пачку необработанных событий с блокировкой строк
    (FOR UPDATE SKIP LOCKED), что позволяет безопасно запускать несколько
    инстансов relay-воркера параллельно без дублирования публикации."""
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING)
        .order_by(OutboxEvent.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def _publish_event(event: OutboxEvent) -> None:
    exchange = _EXCHANGES.get(event.exchange)
    if exchange is None:
        raise RuntimeError(f"Unknown outbox exchange: {event.exchange}")

    await broker.publish(
        event.payload,
        exchange=exchange,
        routing_key=event.routing_key,
    )


async def relay_once(batch_size: int) -> int:
    """Один проход relay: публикует пачку pending-событий. Возвращает число
    успешно опубликованных событий."""
    published = 0
    async with AsyncSessionLocal() as session:
        events = await _fetch_pending_batch(session, batch_size)

        for event in events:
            try:
                await _publish_event(event)
            except Exception as exc:  # noqa: BLE001
                event.attempts += 1
                event.last_error = str(exc)[:2000]
                logger.warning(
                    "Failed to publish outbox event %s (attempt %s): %s",
                    event.id,
                    event.attempts,
                    exc,
                )
            else:
                event.status = OutboxStatus.SENT
                event.processed_at = datetime.now(timezone.utc)
                published += 1
                logger.info("Published outbox event %s (%s)", event.id, event.event_type)

        await session.commit()

    return published


async def run_relay_forever() -> None:
    """Бесконечный цикл relay-воркера: опрашивает outbox_events и публикует
    накопившиеся события в RabbitMQ. При недоступности брокера события
    остаются в статусе pending и будут повторно опубликованы на следующей
    итерации — данные никогда не теряются."""
    logger.info(
        "Outbox relay started (poll_interval=%ss, batch_size=%s)",
        settings.outbox_poll_interval_seconds,
        settings.outbox_batch_size,
    )
    async with broker:
        while True:
            try:
                await relay_once(settings.outbox_batch_size)
            except Exception:  # noqa: BLE001
                logger.exception("Outbox relay iteration failed")
            await asyncio.sleep(settings.outbox_poll_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_relay_forever())
