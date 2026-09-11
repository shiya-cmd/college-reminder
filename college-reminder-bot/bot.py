from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Reminder", callback_data="add_reminder"),
        ],
        [
            InlineKeyboardButton("📋 My Reminders", callback_data="my_reminders"),
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    name = user.first_name or "there"

    message = (
        f"✨ <b>COLLEGE REMINDER</b>\n\n"
        f"Hey {name} 👋\n\n"
        f"Your personal academic sidekick. 🎓\n\n"
        f"Stay on top of assignments, deadlines, "
        f"and everything college throws at you. 🫡\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>Ready to lock in?</b>"
    )

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    if query.data == "add_reminder":
        await query.edit_message_text(
            "➕ <b>Add Reminder</b>\n\n"
            "This feature is coming next. 👀",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="home",
                    )
                ]
            ]),
        )

    elif query.data == "my_reminders":
        await query.edit_message_text(
            "📋 <b>My Reminders</b>\n\n"
            "You don't have any reminders yet. 😌",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "➕ Add Reminder",
                        callback_data="add_reminder",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="home",
                    )
                ],
            ]),
        )

    elif query.data == "stats":
        await query.edit_message_text(
            "📊 <b>Your Stats</b>\n\n"
            "Reminders created: <b>0</b>\n"
            "Completed: <b>0</b>\n"
            "Pending: <b>0</b>\n\n"
            "Time to start cooking. 🔥",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="home",
                    )
                ]
            ]),
        )

    elif query.data == "settings":
        await query.edit_message_text(
            "⚙️ <b>Settings</b>\n\n"
            "Settings will be added later.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="home",
                    )
                ]
            ]),
        )

    elif query.data == "home":
        user = update.effective_user
        name = user.first_name or "there"

        message = (
            f"✨ <b>COLLEGE REMINDER</b>\n\n"
            f"Hey {name} 👋\n\n"
            f"Your personal academic sidekick. 🎓\n\n"
            f"Stay on top of assignments, deadlines, "
            f"and everything college throws at you. 🫡\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔥 <b>Ready to lock in?</b>"
        )

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


def main():
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    print("College Reminder bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()