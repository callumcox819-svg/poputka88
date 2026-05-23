from aiogram import Router

from handlers.mailing import router as mailing_router
from handlers.start import router as start_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(mailing_router)
    return root
