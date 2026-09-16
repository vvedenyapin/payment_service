import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.repositories.payment_repo import PaymentRepository
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentDetailResponse,
)
from app.security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"], dependencies=[Depends(verify_api_key)])


@router.post(
    "",
    response_model=PaymentCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Создать платёж",
)
async def create_payment(
    payload: PaymentCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_db_session),
) -> PaymentCreateResponse:
    repo = PaymentRepository(session)

    # Идемпотентность: если платёж с таким Idempotency-Key уже создавался,
    # возвращаем ранее созданный платёж вместо повторного создания.
    existing = await repo.get_by_idempotency_key(idempotency_key)
    if existing is not None:
        logger.info("Idempotent replay for key=%s -> payment_id=%s", idempotency_key, existing.id)
        return PaymentCreateResponse(
            payment_id=existing.id,
            status=existing.status,
            created_at=existing.created_at,
        )

    try:
        payment = await repo.create_with_outbox_event(
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            metadata=payload.metadata,
            webhook_url=payload.webhook_url,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        # Гонка: два одновременных запроса с одинаковым Idempotency-Key.
        # Уникальный индекс в БД не даст создать дубль — откатываемся
        # и отдаём уже существующую запись.
        await session.rollback()
        existing = await repo.get_by_idempotency_key(idempotency_key)
        if existing is None:  # pragma: no cover - крайне маловероятно
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key conflict")
        return PaymentCreateResponse(
            payment_id=existing.id,
            status=existing.status,
            created_at=existing.created_at,
        )

    return PaymentCreateResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetailResponse,
    summary="Получить информацию о платеже",
)
async def get_payment(
    payment_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> PaymentDetailResponse:
    repo = PaymentRepository(session)
    payment = await repo.get_by_id(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentDetailResponse.model_validate(payment)
