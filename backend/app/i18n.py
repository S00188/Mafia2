"""
Shared language support — one preference, read and written by both the bot
(app/telegram_bot.py) and the webapp (app/api/routes_auth.py hands it to
app/static/app.js on login), so switching language on either side shows up
on the other.

Scope: this covers every message an ordinary PLAYER can see from the bot
(menu, about, stats, roles/group-picker prompts, force-sub gate, the
admin's reply relayed back to them) and the webapp's UI chrome. The bot
owner's own admin panel (app/telegram_bot.py's admin: callbacks) stays
Uzbek-only — it's a tool for whoever runs the bot, not player-facing.
The join message posted into a GROUP chat (post_join_button) also stays
Uzbek-only on purpose: it's a single message shared by everyone in that
group, not tied to any one reader's preference.
"""
from __future__ import annotations
from typing import Optional

from app.database import AsyncSessionLocal
from app.models.models import UserLanguage

SUPPORTED_LANGUAGES = ("uz", "ru", "en")
DEFAULT_LANGUAGE = "uz"

LANGUAGE_LABELS = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

# ------------------------------------------------------ persistent state -
async def get_user_language(telegram_user_id: int) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.get(UserLanguage, telegram_user_id)
        return row.language if row and row.language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


async def set_user_language(telegram_user_id: int, language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    async with AsyncSessionLocal() as session:
        row = await session.get(UserLanguage, telegram_user_id)
        if row is None:
            session.add(UserLanguage(telegram_user_id=telegram_user_id, language=language))
        else:
            row.language = language
        await session.commit()


# ------------------------------------------------------------- buttons ---
# Persistent reply-keyboard buttons are matched by their literal text, so
# each language's label has to be recognized on its own — see
# button_texts() below, used to build the F.text.in_({...}) filters in
# app/telegram_bot.py instead of a single F.text == ... check.
BUTTONS: dict[str, dict[str, str]] = {
    "start_group_game": {
        "uz": "🎮 Guruhda o'yin boshlash",
        "ru": "🎮 Начать игру в группе",
        "en": "🎮 Start game in a group",
    },
    "roles": {
        "uz": "🎭 Rollar",
        "ru": "🎭 Роли",
        "en": "🎭 Roles",
    },
    "my_stats": {
        "uz": "📊 Statistikam",
        "ru": "📊 Моя статистика",
        "en": "📊 My stats",
    },
    "about": {
        "uz": "ℹ️ Bot haqida",
        "ru": "ℹ️ О боте",
        "en": "ℹ️ About the bot",
    },
    "contact_admin": {
        "uz": "👨‍💼 Admin bilan bog'lanish",
        "ru": "👨‍💼 Связаться с админом",
        "en": "👨‍💼 Contact admin",
    },
    "admin_panel": {
        "uz": "🛠 Admin paneli",
        "ru": "🛠 Панель админа",
        "en": "🛠 Admin panel",
    },
}

# Always shown the same way regardless of the current language, since it
# already names all three languages — no translation lookup needed for it.
BTN_LANGUAGE = "🌐 Til / Язык / Language"


def button_text(key: str, lang: str) -> str:
    return BUTTONS[key].get(lang, BUTTONS[key][DEFAULT_LANGUAGE])


def button_texts(key: str) -> set[str]:
    """Every language's label for this button, for F.text.in_(...) filters
    that need to recognize the button regardless of the sender's language."""
    return set(BUTTONS[key].values())


# ------------------------------------------------------------ messages ---
MESSAGES: dict[str, dict[str, str]] = {
    "start_private_welcome": {
        "uz": "👋 Salom! Bu bot guruh o'yinlari uchun.\n\n"
              "Meni biror guruhga qo'shing va o'sha yerda <code>/start</code> "
              "buyrug'ini yuboring — a'zolar qo'shiladigan tugma paydo bo'ladi. "
              "Yoki pastdagi menyudan foydalaning.",
        "ru": "👋 Привет! Этот бот для групповых игр.\n\n"
              "Добавьте меня в группу и отправьте там команду <code>/start</code> — "
              "появится кнопка для присоединения. Либо используйте меню снизу.",
        "en": "👋 Hi! This bot is for group games.\n\n"
              "Add me to a group and send <code>/start</code> there — a join "
              "button will appear. Or use the menu below.",
    },
    "use_menu_below": {
        "uz": "Quyidagi menyudan foydalaning:",
        "ru": "Используйте меню снизу:",
        "en": "Use the menu below:",
    },
    "command_not_understood": {
        "uz": "Buyruq tushunilmadi. Pastdagi menyudan foydalaning:",
        "ru": "Команда не распознана. Используйте меню снизу:",
        "en": "I didn't understand that. Use the menu below:",
    },
    "force_sub_prompt": {
        "uz": "Botdan foydalanish uchun avval quyidagi kanalga a'zo bo'ling, "
              "so'ng \"✅ Tekshirish\" tugmasini bosing.",
        "ru": "Чтобы пользоваться ботом, сначала подпишитесь на канал ниже, "
              "затем нажмите «✅ Проверить».",
        "en": "To use the bot, first join the channel below, then tap "
              "\"✅ Check\".",
    },
    "force_sub_go_to_channel": {
        "uz": "📡 Kanalga o'tish", "ru": "📡 Перейти в канал", "en": "📡 Open channel",
    },
    "force_sub_check": {
        "uz": "✅ Tekshirish", "ru": "✅ Проверить", "en": "✅ Check",
    },
    "force_sub_not_yet": {
        "uz": "Hali kanalga a'zo bo'lmagansiz.",
        "ru": "Вы ещё не подписались на канал.",
        "en": "You haven't joined the channel yet.",
    },
    "force_sub_confirmed": {
        "uz": "✅ Tasdiqlandi!", "ru": "✅ Подтверждено!", "en": "✅ Confirmed!",
    },
    "force_sub_confirmed_body": {
        "uz": "✅ Obuna tasdiqlandi. Endi botdan foydalanishingiz mumkin.",
        "ru": "✅ Подписка подтверждена. Теперь вы можете пользоваться ботом.",
        "en": "✅ Subscription confirmed. You can now use the bot.",
    },
    "about_body": {
        "uz": "🎭 <b>Mafia Mini App</b>\n\n"
              "Guruhlaringizda 6 dan 25 tagacha o'yinchi bilan Mafia o'ynang — "
              "kechasi maxfiy harakatlar, kunduzi muhokama va ovoz berish.\n\n"
              "Boshlash uchun meni istalgan guruhga admin qilib qo'shing va "
              "o'sha yerda <code>/start</code> yuboring.\n\n"
              "{start_group_game} — guruhga chiqmasdan, shu yerdan o'yin havolasini yuborish\n"
              "{roles} — barcha rollar va qobiliyatlari\n"
              "{my_stats} — shaxsiy statistikangiz\n"
              "{contact_admin} — bot admini bilan bog'lanish",
        "ru": "🎭 <b>Mafia Mini App</b>\n\n"
              "Играйте в Мафию в своих группах — от 6 до 25 игроков, тайные "
              "ночные действия, дневные обсуждения и голосование.\n\n"
              "Чтобы начать, добавьте меня администратором в любую группу и "
              "отправьте там <code>/start</code>.\n\n"
              "{start_group_game} — отправить ссылку на игру прямо отсюда\n"
              "{roles} — все роли и их способности\n"
              "{my_stats} — ваша личная статистика\n"
              "{contact_admin} — связаться с администратором бота",
        "en": "🎭 <b>Mafia Mini App</b>\n\n"
              "Play Mafia in your groups — 6 to 25 players, secret night "
              "actions, day discussion and voting.\n\n"
              "To start, add me as an admin to any group and send "
              "<code>/start</code> there.\n\n"
              "{start_group_game} — send the game link right from here\n"
              "{roles} — every role and its ability\n"
              "{my_stats} — your personal stats\n"
              "{contact_admin} — contact the bot's admin",
    },
    "stats_none_yet": {
        "uz": "Siz hali birorta o'yinni yakunlamagansiz. Guruhda o'ynab ko'ring!",
        "ru": "Вы ещё не завершили ни одной игры. Сыграйте в группе!",
        "en": "You haven't finished a game yet. Try playing in a group!",
    },
    "stats_body": {
        "uz": "📊 <b>Statistikangiz</b>\n\n"
              "O'ynagan o'yinlar: <b>{games_played}</b>\n"
              "G'alabalar: <b>{wins}</b> ({win_rate}%)\n"
              "Mag'lubiyatlar: <b>{losses}</b>\n\n"
              "🏙 Shahar g'alabalari: {town_wins}\n"
              "🔫 Mafiya g'alabalari: {mafia_wins}\n"
              "🎭 Neytral g'alabalari: {neutral_wins}",
        "ru": "📊 <b>Ваша статистика</b>\n\n"
              "Сыграно игр: <b>{games_played}</b>\n"
              "Побед: <b>{wins}</b> ({win_rate}%)\n"
              "Поражений: <b>{losses}</b>\n\n"
              "🏙 Побед за Город: {town_wins}\n"
              "🔫 Побед за Мафию: {mafia_wins}\n"
              "🎭 Побед за Нейтралов: {neutral_wins}",
        "en": "📊 <b>Your stats</b>\n\n"
              "Games played: <b>{games_played}</b>\n"
              "Wins: <b>{wins}</b> ({win_rate}%)\n"
              "Losses: <b>{losses}</b>\n\n"
              "🏙 Town wins: {town_wins}\n"
              "🔫 Mafia wins: {mafia_wins}\n"
              "🎭 Neutral wins: {neutral_wins}",
    },
    "roles_prompt": {
        "uz": "Barcha rollar va ularning qobiliyatlari:",
        "ru": "Все роли и их способности:",
        "en": "Every role and its ability:",
    },
    "roles_open_button": {
        "uz": "🎭 Rollarni ko'rish", "ru": "🎭 Смотреть роли", "en": "🎭 View roles",
    },
    "no_groups_known": {
        "uz": "Hali hech qanday guruh topilmadi. Avval meni biror guruhga "
              "admin qilib qo'shing.",
        "ru": "Группы пока не найдены. Сначала добавьте меня администратором "
              "в какую-нибудь группу.",
        "en": "No groups found yet. First add me as an admin to a group.",
    },
    "no_matching_groups": {
        "uz": "Siz a'zo bo'lgan guruhlardan birortasida meni topa olmadim. "
              "Guruhga o'zingiz a'zo ekaningizga ishonch hosil qiling.",
        "ru": "Не нашёл меня ни в одной группе, где состоите вы. Убедитесь, "
              "что вы действительно состоите в этой группе.",
        "en": "I couldn't find myself in any group you're a member of. "
              "Make sure you're actually a member of that group.",
    },
    "pick_a_group": {
        "uz": "Qaysi guruhda o'yin boshlaymiz?",
        "ru": "В какой группе начнём игру?",
        "en": "Which group should we start the game in?",
    },
    "not_a_member_alert": {
        "uz": "Siz bu guruh a'zosi emassiz.",
        "ru": "Вы не состоите в этой группе.",
        "en": "You're not a member of that group.",
    },
    "could_not_post_to_group": {
        "uz": "Guruhga xabar yubora olmadim — men o'sha guruhdan chiqarilgan bo'lishim mumkin.",
        "ru": "Не удалось отправить сообщение в группу — возможно, меня удалили оттуда.",
        "en": "Couldn't post to that group — I may have been removed from it.",
    },
    "sent_confirmation": {
        "uz": "✅ Yuborildi!", "ru": "✅ Отправлено!", "en": "✅ Sent!",
    },
    "group_link_sent": {
        "uz": "✅ Guruhga o'yin havolasi yuborildi.",
        "ru": "✅ Ссылка на игру отправлена в группу.",
        "en": "✅ Game link sent to the group.",
    },
    "admin_not_configured": {
        "uz": "Hozircha admin sozlanmagan.",
        "ru": "Администратор пока не настроен.",
        "en": "No admin is configured yet.",
    },
    "ask_admin_message": {
        "uz": "✍️ Xabaringizni yozing — u to'g'ridan-to'g'ri botning adminiga "
              "yuboriladi. Admin javob yozganda, siz uni shu yerda ko'rasiz.",
        "ru": "✍️ Напишите ваше сообщение — оно будет отправлено "
              "администратору бота напрямую. Когда админ ответит, вы "
              "увидите это здесь.",
        "en": "✍️ Type your message — it'll be sent straight to the bot's "
              "admin. When they reply, you'll see it here.",
    },
    "admin_message_sent": {
        "uz": "✅ Xabaringiz adminga yuborildi. Javobni shu yerda kuting.",
        "ru": "✅ Ваше сообщение отправлено администратору. Ждите ответ здесь.",
        "en": "✅ Your message was sent to the admin. Wait for a reply here.",
    },
    "admin_message_failed": {
        "uz": "Adminga yubora olmadim — admin botni hali ishga tushirmagan bo'lishi mumkin.",
        "ru": "Не удалось отправить администратору — возможно, он ещё не "
              "запускал бота.",
        "en": "Couldn't reach the admin — they may not have started the bot yet.",
    },
    "admin_reply_label": {
        "uz": "👨‍💼 <b>Admin javobi:</b>\n\n{text}",
        "ru": "👨‍💼 <b>Ответ администратора:</b>\n\n{text}",
        "en": "👨‍💼 <b>Admin's reply:</b>\n\n{text}",
    },
    "language_prompt": {
        "uz": "Tilni tanlang:", "ru": "Выберите язык:", "en": "Choose your language:",
    },
    "language_set": {
        "uz": "✅ Til o'zbekchaga o'zgartirildi.",
        "ru": "✅ Язык изменён на русский.",
        "en": "✅ Language changed to English.",
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    text = MESSAGES[key].get(lang, MESSAGES[key][DEFAULT_LANGUAGE])
    return text.format(**kwargs) if kwargs else text
