from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://payments:payments@localhost:5432/payments"

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # API auth
    api_key: str = "super-secret-api-key"

    # Outbox relay worker
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 20

    # Payment gateway emulation
    gateway_min_delay_seconds: float = 2.0
    gateway_max_delay_seconds: float = 5.0
    gateway_success_rate: float = 0.9

    # Webhook delivery retries
    webhook_max_retries: int = 3
    webhook_base_backoff_seconds: float = 1.0
    webhook_timeout_seconds: float = 5.0

    # Message (consumer) processing retries before DLQ
    message_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
