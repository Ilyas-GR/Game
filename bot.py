"""Telegram-бот MMO RPG. Вся игровая логика — в game/engine.py."""
import logging
import os
import tempfile

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

from game.engine import Game, Reply
from game.items import ITEMS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Создай файл .env по образцу .env.example")

ADMINS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split()}
INVITE_ONLY = os.getenv("INVITE_ONLY", "0").lower() in ("1", "true", "yes")

bot = telebot.TeleBot(TOKEN)
game = Game(os.getenv("DB_PATH", "game.db"), invite_only=INVITE_ONLY, admins=ADMINS)

MOVES = {
    "⬆️ Север": (0, 1), "⬇️ Юг": (0, -1), "⬅️ Запад": (-1, 0), "➡️ Восток": (1, 0),
    # кнопки старой версии игры
    "North": (0, 1), "South": (0, -1), "West": (-1, 0), "East": (1, 0),
}
SCREENS = {
    "🔍 Осмотреться": game.look,
    "📜 Герой": game.hero,
    "🎒 Рюкзак": game.bag,
    "🛡 Снаряжение": game.gear,
    "🗺 Карта": game.world_map,
}

HELP = """📖 Как играть

Ходи кнопками ⬆️⬇️⬅️➡️ по карте 11×11. Лагерь 🏕 в центре — там безопасно, можно отдохнуть и поторговать.

⚔️ Нажми на врага, чтобы атаковать. Волки, гоблины, бандиты и орки нападают сами!
🧰 Сундуки охраняются — сначала победи стражу. Добычу забирает тот, кто успел первым.
👑 Боссы: Король гоблинов (шахты), Вождь орков, Главарь бандитов. Опыт получают все, кто бил.
⛏ В шахтах можно добывать руду, 🎣 на пруду — рыбачить.
🌊 Реку можно перейти только по мостам.

Любой текст — сообщение игрокам в той же локации.

/top — рейтинг героев
/online — кто в игре
/help — эта справка"""


def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🎒 Рюкзак", "⬆️ Север", "📜 Герой")
    markup.row("⬅️ Запад", "🔍 Осмотреться", "➡️ Восток")
    markup.row("🛡 Снаряжение", "⬇️ Юг", "🗺 Карта")
    return markup


def inline(buttons):
    if not buttons:
        return None
    markup = types.InlineKeyboardMarkup()
    for row in buttons:
        markup.row(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in row])
    return markup


def deliver(notify):
    for uid, text in notify:
        try:
            bot.send_message(uid, text)
        except ApiTelegramException as e:
            log.info("Не удалось уведомить %s: %s", uid, e)


def send(chat_id, reply, keyboard=None):
    bot.send_message(chat_id, reply.text, reply_markup=keyboard or inline(reply.buttons))
    deliver(reply.notify)


def edit(message, reply):
    try:
        bot.edit_message_text(reply.text, message.chat.id, message.message_id,
                              reply_markup=inline(reply.buttons))
    except ApiTelegramException as e:
        if "message is not modified" not in str(e):
            log.warning("Не удалось изменить сообщение: %s", e)
            bot.send_message(message.chat.id, reply.text, reply_markup=inline(reply.buttons))
    deliver(reply.notify)


def private_only(message):
    if message.chat.type == "private":
        return True
    bot.reply_to(message, "Играть можно только в личных сообщениях с ботом.")
    return False


def ask_for_setup(message, stage):
    """Ведёт нового игрока по шагам: инвайт → имя → характеристики."""
    uid = message.from_user.id
    if stage == "invite":
        bot.send_message(message.chat.id, "🔐 Игра пока закрытая. Введи пригласительный код:",
                         reply_markup=types.ReplyKeyboardRemove())
    elif stage == "name":
        bot.send_message(message.chat.id, "🏰 Добро пожаловать в Приграничье!\n\n"
                         "✨ Как будут звать твоего героя? (2–16 символов)",
                         reply_markup=types.ReplyKeyboardRemove())
    elif stage == "stats":
        send(message.chat.id, game.stats(uid))


def enter_world(chat_id, uid, greeting):
    send(chat_id, greeting, keyboard=main_keyboard())
    send(chat_id, game.look(uid))


# ---------- команды ----------

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not private_only(message):
        return
    uid = message.from_user.id
    stage = game.stage(uid)
    if stage != "play":
        return ask_for_setup(message, stage)
    enter_world(message.chat.id, uid,
                Reply(f"С возвращением! Сейчас в мире героев: {game.online_count()}"))


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP)


@bot.message_handler(commands=["top"])
def cmd_top(message):
    send(message.chat.id, game.top())


@bot.message_handler(commands=["online"])
def cmd_online(message):
    bot.send_message(message.chat.id, f"🟢 Сейчас в мире героев: {game.online_count()}")


# ---------- админ ----------

def is_admin(message):
    return message.from_user.id in ADMINS


@bot.message_handler(commands=["admin"], func=is_admin)
def cmd_admin(message):
    send(message.chat.id, game.admin_stats())


@bot.message_handler(commands=["gen"], func=is_admin)
def cmd_gen(message):
    bot.send_message(message.chat.id, f"🎟 Новый инвайт-код: {game.new_invite()}")


@bot.message_handler(commands=["items"], func=is_admin)
def cmd_items(message):
    bot.send_message(message.chat.id, "\n".join(f"{key} — {item.label}" for key, item in ITEMS.items()))


@bot.message_handler(commands=["give"], func=is_admin)
def cmd_give(message):
    args = message.text.split()[1:]
    if not args:
        return bot.send_message(message.chat.id, "Использование: /give <предмет> [кол-во]")
    count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
    send(message.chat.id, game.give(message.from_user.id, args[0], count))


@bot.message_handler(commands=["backup"], func=is_admin)
def cmd_backup(message):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "game.db")
        game.backup(path)
        with open(path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="📦 Резервная копия базы")


# ---------- текст ----------

@bot.message_handler(content_types=["text"])
def on_text(message):
    if not private_only(message):
        return
    uid = message.from_user.id
    text = message.text
    stage = game.stage(uid)

    if stage == "invite":
        reply = game.redeem(uid, text)
        send(message.chat.id, reply)
        if game.stage(uid) == "name":
            ask_for_setup(message, "name")
        return
    if stage == "name":
        return send(message.chat.id, game.set_name(uid, text))
    if stage == "stats":
        return ask_for_setup(message, stage)

    if text in MOVES:
        reply = game.move(uid, *MOVES[text])
    elif text in SCREENS:
        reply = SCREENS[text](uid)
    elif text.startswith("/"):
        reply = Reply("Неизвестная команда. Справка: /help")
    else:
        reply = game.say(uid, text)
    send(message.chat.id, reply)


# ---------- инлайн-кнопки ----------

ACTIONS = {
    "look": lambda uid, a: game.look(uid),
    "atk": lambda uid, a: game.attack(uid, int(a[0])),
    "flee": lambda uid, a: game.flee(uid),
    "chest": lambda uid, a: game.open_chest(uid),
    "gather": lambda uid, a: game.gather(uid),
    "rest": lambda uid, a: game.rest(uid),
    "shop": lambda uid, a: game.shop(uid),
    "buy": lambda uid, a: game.buy(uid, a[0]),
    "sell": lambda uid, a: game.sell(uid, a[0]),
    "hero": lambda uid, a: game.hero(uid),
    "stats": lambda uid, a: game.stats(uid),
    "bag": lambda uid, a: game.bag(uid),
    "gear": lambda uid, a: game.gear(uid),
    "inv": lambda uid, a: game.item(uid, a[0]),
    "use": lambda uid, a: game.use(uid, a[0], a[1] if len(a) > 1 else "look"),
    "eq": lambda uid, a: game.equip(uid, a[0]),
    "uneq": lambda uid, a: game.unequip(uid, a[0]),
    "drop": lambda uid, a: game.drop(uid, a[0]),
}
SETUP_ACTIONS = {
    "s+": lambda uid, a: game.change_stat(uid, a[0], 1),
    "s-": lambda uid, a: game.change_stat(uid, a[0], -1),
}


@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    uid = call.from_user.id
    action, *args = call.data.split(":")
    stage = game.stage(uid)

    if action == "sdone":
        greeting = game.finish_creation(uid)
        if greeting is None:
            return bot.answer_callback_query(call.id, "Сначала распредели все очки!")
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
        return enter_world(call.message.chat.id, uid, greeting)

    handler = SETUP_ACTIONS.get(action)
    if handler is None and stage == "play":
        handler = ACTIONS.get(action)
    if handler is None:
        return bot.answer_callback_query(call.id)
    try:
        reply = handler(uid, args)
    except (ValueError, IndexError, KeyError):
        return bot.answer_callback_query(call.id, "Кнопка устарела.")
    bot.answer_callback_query(call.id)
    edit(call.message, reply)


if __name__ == "__main__":
    log.info("Бот запущен. Админы: %s, вход по инвайтам: %s", ADMINS or "нет", INVITE_ONLY)
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
