from aiogram.fsm.state import State, StatesGroup


class NewCampaign(StatesGroup):
    subject = State()
    body = State()
    format_choice = State()
    encoding = State()
    recipients = State()


class QuickAdd(StatesGroup):
    sender_name = State()
    accounts = State()


class MailReply(StatesGroup):
    waiting_text = State()


class LeadPrice(StatesGroup):
    waiting_price = State()

