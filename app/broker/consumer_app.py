"""Точка входа для запуска consumer-процесса:

    faststream run app.broker.consumer_app:app

Импорт app.broker.consumer регистрирует подписчика на очередь payments.new
на общем broker-объекте (app.broker.broker.broker). При старте дополнительно
объявляются exchange/queue для Dead Letter Queue, куда consumer вручную
публикует сообщения, не обработанные после MESSAGE_MAX_RETRIES попыток.
"""

from faststream import FastStream

from app.broker import consumer  # noqa: F401  (регистрирует subscriber)
from app.broker.broker import broker, dlx_exchange, payments_new_dlq

app = FastStream(broker)


@app.after_startup
async def _declare_dead_letter_topology() -> None:
    dlx = await broker.declare_exchange(dlx_exchange)
    dlq = await broker.declare_queue(payments_new_dlq)
    await dlq.bind(dlx, routing_key=payments_new_dlq.routing_key)
