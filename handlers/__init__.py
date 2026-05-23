from aiogram import Router

from handlers.accounts import router as accounts_router
from handlers.mailing import router as mailing_router
from handlers.menu import router as menu_router
from handlers.settings import router as settings_router
from handlers.gag_settings import router as gag_settings_router
from handlers.settings_accounts import router as settings_accounts_router
from handlers.proxies import router as proxies_router
from handlers.templates import router as templates_router
from handlers.start import router as start_router
from handlers.status import router as status_router
from handlers.json_incoming import router as json_incoming_router
from handlers.incoming_mail import router as incoming_mail_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(menu_router)
    root.include_router(start_router)
    root.include_router(status_router)
    root.include_router(settings_router)
    root.include_router(gag_settings_router)
    root.include_router(proxies_router)
    root.include_router(templates_router)
    root.include_router(settings_accounts_router)
    root.include_router(accounts_router)
    root.include_router(mailing_router)
    root.include_router(incoming_mail_router)
    root.include_router(json_incoming_router)
    return root
