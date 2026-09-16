from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import settings

# --- Топология RabbitMQ -----------------------------------------------------
#
# exchange "payments" (topic)
#     └── queue "payments.new"  (routing_key="payments.new")
#             при финальном failure (после MESSAGE_MAX_RETRIES попыток)
#             сообщение публикуется вручную в DLX:
# exchange "payments.dlx" (topic)
#     └── queue "payments.new.dlq" (routing_key="payments.new.dlq")
#
# Ретраи между попытками реализованы на уровне приложения (см. consumer.py):
# счётчик попыток передаётся в заголовке сообщения "x-retry-count", а не через
# нативный requeue RabbitMQ — это даёт полный контроль над количеством попыток
# и экспоненциальной задержкой перед повторной обработкой.

broker = RabbitBroker(settings.rabbitmq_url)

payments_exchange = RabbitExchange("payments", type=ExchangeType.TOPIC, durable=True)
dlx_exchange = RabbitExchange("payments.dlx", type=ExchangeType.TOPIC, durable=True)

payments_new_queue = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key="payments.new",
)

payments_new_dlq = RabbitQueue(
    "payments.new.dlq",
    durable=True,
    routing_key="payments.new.dlq",
)
