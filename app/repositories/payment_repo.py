import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.payment import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        result = await self.session.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def create_with_outbox_event(
        self,
        *,
        amount,
        currency,
        description,
        metadata,
        webhook_url,
        idempotency_key,
    ) -> Payment:
        """Атомарно создаёт платёж и связанное outbox-событие в одной транзакции —
        это и есть суть Outbox pattern: событие гарантированно попадёт в БД
        вместе с бизнес-изменением, а публикация в брокер выполняется отдельно
        (см. app/outbox/relay.py), поэтому недоступность RabbitMQ в момент запроса
        не приводит к потере события."""
        payment = Payment(
            amount=amount,
            currency=currency,
            description=description,
            payment_metadata=metadata,
            webhook_url=str(webhook_url),
            idempotency_key=idempotency_key,
            status=PaymentStatus.PENDING,
        )
        self.session.add(payment)
        await self.session.flush()  # получаем payment.id и created_at (server_default)
        await self.session.refresh(payment)

        event = OutboxEvent(
            aggregate_type="payment",
            aggregate_id=payment.id,
            event_type="payment.new",
            exchange="payments",
            routing_key="payments.new",
            payload={
                "payment_id": str(payment.id),
                "amount": str(payment.amount),
                "currency": payment.currency.value,
                "webhook_url": payment.webhook_url,
                "idempotency_key": payment.idempotency_key,
                "created_at": payment.created_at.isoformat(),
            },
        )
        self.session.add(event)

        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def update_status(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
    ) -> Payment | None:
        payment = await self.get_by_id(payment_id)
        if payment is None:
            return None
        payment.status = status
        payment.processed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment
