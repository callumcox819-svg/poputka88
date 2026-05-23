from aiogram.fsm.state import State, StatesGroup


class NewCampaign(StatesGroup):
    subject = State()
    body = State()
    format_choice = State()
    encoding = State()
    recipients = State()
