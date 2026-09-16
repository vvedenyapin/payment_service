import asyncio
import random

from app.config import settings
from app.models.payment import PaymentStatus


async def emulate_payment_processing() -> PaymentStatus:
    """Эмулирует обращение к внешнему платёжному шлюзу:
    задержка 2-5 сек, 90% успех / 10% ошибка (настраивается через .env)."""
    delay = random.uniform(
        settings.gateway_min_delay_seconds, settings.gateway_max_delay_seconds
    )
    await asyncio.sleep(delay)

    is_success = random.random() < settings.gateway_success_rate
    return PaymentStatus.SUCCEEDED if is_success else PaymentStatus.FAILED
