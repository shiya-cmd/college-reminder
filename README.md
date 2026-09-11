# Bennett College Reminder Telegram Bot

This version is built around the supplied Bennett Moodle scraper.

## Behavior

- Username/password are entered once.
- Password is encrypted locally.
- Moodle cookies are stored separately for each Telegram user.
- Cookies are tried first.
- If Moodle logs the session out, the bot automatically logs in using the saved credentials.
- It checks the Bennett LMS calendar every hour.
- It uses the supplied assignment selector:
  `[data-type="event"][data-event-component="mod_assign"]`
- Only `data-event-eventtype="due"` events are treated as assignments.
- New assignments are sent to Telegram immediately after discovery.
- Reminders are sent approximately 10 hours and 2 hours before the due time.
- Each assignment has a `Completed` button.
- Pressing `Completed` permanently stops reminders for that assignment.
- `/logout` deletes credentials, cookies, and assignments.

## Setup

### 1. Create bot

In Telegram open BotFather and use `/newbot`.

Copy the bot token.

### 2. Install

Python 3.10+:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment

```bash
cp .env.example .env
```

Generate encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the result into `.env`:

```env
BOT_TOKEN=YOUR_BOT_TOKEN
CREDENTIAL_KEY=YOUR_GENERATED_FERNET_KEY
```

Do not commit `.env`.

### 4. Run

```bash
python bot.py
```

Then open your Telegram bot and send:

```text
/start
```

Enter your Bennett LMS username and password.

After that, the bot handles authentication and hourly checking automatically.

## Commands

```text
/start
/assignments
/completed
/sync
/status
/logout
/help
```

## Data

Runtime data is stored under:

```text
data/
├── college_reminder.db
└── cookies/
    └── TELEGRAM_USER_ID.json
```

Do not publish the `data` directory because it contains authentication material.

## Reminder behavior

The bot checks every hour. Therefore reminders are sent during the hourly check window around:

- 10 hours before due
- 2 hours before due

The Completed button overrides both reminders.

## Important scraper note

The assignment extraction intentionally follows the supplied scraper. If Bennett changes its Moodle HTML, `lms.py` is the place to update the scraper.
