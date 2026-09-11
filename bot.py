import logging
import time
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import BOT_TOKEN, TIMEZONE, SYNC_INTERVAL
from database import (
    init_database,
    get_account,
    save_account,
    delete_account,
    upsert_assignment,
    get_assignments,
    get_assignment,
    mark_completed,
    get_users,
    get_pending_reminders,
    mark_new_alert_sent,
    mark_reminder_sent
)
from storage import encrypt_password, decrypt_password, delete_cookies
from lms import LMS

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("college-reminder")

USERNAME, PASSWORD = range(2)

def due_text(ts):
    if ts is None:
        return "Due time unavailable"
    return datetime.fromtimestamp(ts, TIMEZONE).strftime(
        "%d %b %Y, %I:%M %p"
    )

def reminder_keyboard(assignment_id, url=None):
    rows = []

    if url:
        rows.append([
            InlineKeyboardButton("🔗 Open Assignment", url=url)
        ])

    rows.append([
        InlineKeyboardButton(
            "✅ Completed",
            callback_data=f"complete:{assignment_id}"
        )
    ])

    return InlineKeyboardMarkup(rows)

def assignment_message(row, heading="📚 Assignment"):
    course_id = row["course_id"] or "Bennett LMS"

    text = (
        f"<b>{heading}</b>\n\n"
        f"📚 Course: <b>{course_id}</b>\n"
        f"📝 <b>{row['title']}</b>\n"
        f"⏰ Due: <b>{due_text(row['due'])}</b>"
    )

    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    account = get_account(uid)

    if account:
        await update.message.reply_text(
            "✅ <b>Bennett LMS is already connected.</b>\n\n"
            "I will keep checking the LMS automatically every hour.\n"
            "You do not need to enter your username/password again.\n\n"
            "Use /assignments to see assignments or /sync to check now.",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎓 <b>College Reminder</b>\n\n"
        "Connect your Bennett LMS account.\n\n"
        "You will enter your LMS username and password <b>once</b>.",
        parse_mode=ParseMode.HTML
    )

    await update.message.reply_text("👤 Send your Bennett LMS username:")
    return USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()

    if not username:
        await update.message.reply_text("Username cannot be empty. Try again:")
        return USERNAME

    context.user_data["lms_username"] = username

    await update.message.reply_text(
        "🔐 Send your Bennett LMS password.\n\n"
        "Your password message will be deleted immediately after receiving it."
    )
    return PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    password = update.message.text
    username = context.user_data.pop("lms_username", "")

    # Delete the plaintext password message from Telegram chat if possible.
    try:
        await update.message.delete()
    except Exception:
        pass

    await update.effective_chat.send_message(
        "🔐 Logging into Bennett LMS..."
    )

    lms = LMS(uid)
    ok, message = lms.login(username, password)

    if not ok:
        await update.effective_chat.send_message(
            f"❌ {message}\n\nUse /start to try again."
        )
        return ConversationHandler.END

    now = time.time()
    encrypted = encrypt_password(password)
    save_account(uid, username, encrypted, now)

    await update.effective_chat.send_message(
        "✅ <b>Login successful.</b>\n\n"
        "Credentials saved securely.\n"
        "I will now check the LMS automatically every hour.",
        parse_mode=ParseMode.HTML
    )

    await sync_user(uid, update.effective_chat.id, context, notify_new=True)

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("lms_username", None)
    await update.message.reply_text("Cancelled. Use /start when ready.")
    return ConversationHandler.END

async def sync_user(uid, chat_id, context, notify_new=True):
    account = get_account(uid)

    if not account:
        if chat_id:
            await context.bot.send_message(
                chat_id,
                "❌ No LMS account connected. Use /start."
            )
        return False

    try:
        password = decrypt_password(account["password_encrypted"])
    except Exception:
        if chat_id:
            await context.bot.send_message(
                chat_id,
                "❌ Saved credentials cannot be decrypted. Please reconnect with /start."
            )
        return False

    lms = LMS(uid)
    ok, result, did_login = lms.ensure_login(
        account["username"],
        password
    )

    if not ok:
        if chat_id:
            await context.bot.send_message(
                chat_id,
                "❌ LMS login failed. Your saved credentials may no longer work. "
                "Use /start to reconnect."
            )
        return False

    html = result
    assignments = lms.scrape_assignments(html)
    now = time.time()

    new_rows = []

    for assignment in assignments:
        is_new = upsert_assignment(uid, assignment, now)
        if is_new:
            # Fetch the inserted row for the Telegram message.
            rows = get_assignments(uid, include_completed=True)
            matching = [
                r for r in rows
                if r["event_id"] == str(assignment["event_id"])
            ]
            if matching:
                new_rows.append(matching[0])

    if notify_new:
        for row in new_rows:
            await send_new_assignment(context, uid, row)

    return True

async def send_new_assignment(context, uid, row):
    text = assignment_message(row, "🆕 NEW ASSIGNMENT")

    text += (
        "\n\n🔔 Reminders will be sent approximately "
        "<b>10 hours</b> and <b>2 hours</b> before the deadline."
    )

    await context.bot.send_message(
        chat_id=uid,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reminder_keyboard(row["id"], row["url"]),
        disable_web_page_preview=True
    )

    mark_new_alert_sent(uid, row["id"])

async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Checking Bennett LMS...")
    ok = await sync_user(
        update.effective_user.id,
        update.effective_chat.id,
        context,
        notify_new=True
    )

    if ok:
        await update.message.reply_text("✅ LMS check complete.")

async def assignments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = get_assignments(uid)

    if not rows:
        await update.message.reply_text(
            "📭 No pending assignments.\n\nUse /sync to check Bennett LMS."
        )
        return

    await update.message.reply_text(
        f"📋 <b>Pending Assignments: {len(rows)}</b>",
        parse_mode=ParseMode.HTML
    )

    for row in rows[:30]:
        await update.message.reply_text(
            assignment_message(row),
            parse_mode=ParseMode.HTML,
            reply_markup=reminder_keyboard(row["id"], row["url"]),
            disable_web_page_preview=True
        )

async def completed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = [
        r for r in get_assignments(uid, include_completed=True)
        if r["completed"]
    ]

    if not rows:
        await update.message.reply_text("No completed assignments yet.")
        return

    text = "✅ <b>Completed Assignments</b>\n\n"
    for row in rows[:30]:
        text += (
            f"• {row['title']} — {due_text(row['due'])}\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    account = get_account(uid)

    if not account:
        await update.message.reply_text(
            "🔴 Not connected.\nUse /start."
        )
        return

    rows = get_assignments(uid, include_completed=True)
    pending = [r for r in rows if not r["completed"]]
    completed = [r for r in rows if r["completed"]]

    await update.message.reply_text(
        "🟢 <b>College Reminder Status</b>\n\n"
        "LMS: Connected\n"
        f"Assignments: {len(rows)}\n"
        f"Pending: {len(pending)}\n"
        f"Completed: {len(completed)}\n"
        "Automatic scraping: Every 1 hour\n"
        "Reminders: 10h + 2h\n"
        "Timezone: Asia/Kolkata",
        parse_mode=ParseMode.HTML
    )

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    delete_account(uid)
    delete_cookies(uid)

    await update.message.reply_text(
        "🔓 <b>Logged out.</b>\n\n"
        "Saved LMS credentials, cookies and assignment data for this Telegram account "
        "have been removed.\n\n"
        "Use /start to connect again.",
        parse_mode=ParseMode.HTML
    )

async def complete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    try:
        assignment_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Invalid assignment.", show_alert=True)
        return

    row = get_assignment(uid, assignment_id)

    if not row:
        await query.answer("Assignment not found.", show_alert=True)
        return

    if row["completed"]:
        await query.answer("Already completed.")
        return

    mark_completed(uid, assignment_id)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        f"✅ <b>Completed</b>\n\n"
        f"📝 {row['title']}\n\n"
        "No further reminders will be sent for this assignment.",
        parse_mode=ParseMode.HTML
    )

async def hourly_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Starting hourly LMS check.")

    users = get_users()

    for uid in users:
        try:
            await sync_user(
                uid,
                uid,
                context,
                notify_new=True
            )
        except Exception:
            logger.exception("Hourly sync failed for user %s", uid)

    await reminder_job(context)

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()

    for uid in get_users():
        try:
            rows = get_pending_reminders(uid, now)

            for row in rows:
                remaining = row["due"] - now

                # Hourly checks mean the actual send can be within the
                # current hourly window around the requested reminder.
                if (
                    not row["reminder_10_sent"]
                    and 9 * 3600 <= remaining <= 10 * 3600 + 3599
                ):
                    await send_reminder(
                        context, uid, row, 10
                    )

                elif (
                    not row["reminder_2_sent"]
                    and 1 * 3600 <= remaining <= 2 * 3600 + 3599
                ):
                    await send_reminder(
                        context, uid, row, 2
                    )

        except Exception:
            logger.exception("Reminder check failed for user %s", uid)

async def send_reminder(context, uid, row, hours):
    text = assignment_message(
        row,
        f"🔔 {hours}-HOUR REMINDER"
    )

    text += (
        f"\n\n⏳ This assignment is due in approximately "
        f"<b>{hours} hours</b>."
        "\n\nPress <b>Completed</b> to stop all further reminders."
    )

    await context.bot.send_message(
        chat_id=uid,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reminder_keyboard(row["id"], row["url"]),
        disable_web_page_preview=True
    )

    mark_reminder_sent(uid, row["id"], hours)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 <b>College Reminder</b>\n\n"
        "/start — connect Bennett LMS once\n"
        "/assignments — pending assignments\n"
        "/completed — completed assignments\n"
        "/sync — check LMS immediately\n"
        "/status — bot/account status\n"
        "/logout — remove account\n"
        "/help — this help",
        parse_mode=ParseMode.HTML
    )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing from .env")

    init_database()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    login_flow = ConversationHandler(
        entry_points=[
            CommandHandler("start", start)
        ],
        states={
            USERNAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_username
                )
            ],
            PASSWORD: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_password
                )
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel)
        ],
        allow_reentry=True
    )

    app.add_handler(login_flow)
    app.add_handler(CommandHandler("assignments", assignments_command))
    app.add_handler(CommandHandler("completed", completed_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(
        CallbackQueryHandler(
            complete_callback,
            pattern=r"^complete:\d+$"
        )
    )

    # First check shortly after startup, then every hour.
    if app.job_queue:
        app.job_queue.run_repeating(
            hourly_job,
            interval=SYNC_INTERVAL,
            first=10
        )

    logger.info("College Reminder Bot running.")
    app.run_polling()

if __name__ == "__main__":
    main()
