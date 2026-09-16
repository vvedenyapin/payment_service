import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.payments import router as payments_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Payment API starting up")
    yield
    logger.info("Payment API shutting down")


app = FastAPI(
    title="Async Payment Processing Service",
    description="Асинхронный сервис процессинга платежей (тестовое задание).",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(payments_router)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
