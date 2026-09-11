import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

from config import BASE_URL, CALENDAR_URL, CALENDAR_TIME, TIMEZONE
from storage import save_cookies, load_cookies, delete_cookies

class LMS:
    def __init__(self, user_id):
        self.user_id = user_id
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140 Safari/537.36"
            )
        })

        # Cookie/session reuse is the first authentication attempt.
        load_cookies(user_id, self.session)

    def looks_logged_out(self, response):
        soup = BeautifulSoup(response.text, "html.parser")

        login_form = soup.find("form", id="login")
        if login_form:
            return True

        if "login/index.php" in response.url:
            return True

        return False

    def calendar(self):
        try:
            response = self.session.get(
                CALENDAR_URL,
                params={"time": CALENDAR_TIME},
                timeout=20
            )
            response.raise_for_status()

            if self.looks_logged_out(response):
                return None

            return response.text
        except requests.RequestException:
            return None

    def login(self, username, password):
        try:
            response = self.session.get(
                BASE_URL + "/login/index.php",
                timeout=20
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            login_form = soup.find("form")

            if not login_form:
                return False, "Could not find Moodle login form."

            action = login_form.get("action")
            if not action:
                action = BASE_URL + "/login/index.php"

            data = {}
            for field in login_form.find_all("input"):
                name = field.get("name")
                value = field.get("value", "")
                if name:
                    data[name] = value

            data["username"] = username
            data["password"] = password

            response = self.session.post(
                action,
                data=data,
                timeout=20,
                allow_redirects=True
            )
            response.raise_for_status()

            if self.looks_logged_out(response):
                return False, "Invalid LMS username or password."

            save_cookies(self.user_id, self.session)
            return True, "Login successful."

        except requests.RequestException as e:
            return False, f"LMS connection error: {e}"

    def ensure_login(self, username, password):
        # First try existing cookies.
        html = self.calendar()
        if html is not None:
            return True, html, False

        # Cookies expired: login using the saved credentials.
        ok, message = self.login(username, password)
        if not ok:
            delete_cookies(self.user_id)
            return False, message, True

        html = self.calendar()
        if html is None:
            return False, "Calendar unavailable after login.", True

        return True, html, True

    def scrape_assignments(self, html):
        soup = BeautifulSoup(html, "html.parser")
        assignments = []

        events = soup.select(
            '[data-type="event"][data-event-component="mod_assign"]'
        )

        for event in events:
            event_type = event.get("data-event-eventtype")

            if event_type != "due":
                continue

            title = event.get("data-event-title")

            if not title:
                title_element = event.select_one(".name")
                if title_element:
                    title = title_element.get_text(" ", strip=True)

            event_id = event.get("data-event-id")
            course_id = event.get("data-course-id")

            link = event.select_one(
                'a[href*="/mod/assign/view.php"]'
            )

            assignment_url = None
            if link:
                assignment_url = link.get("href")
                if assignment_url and assignment_url.startswith("/"):
                    assignment_url = BASE_URL + assignment_url

            due = self.extract_due(event)

            # Event ID is essential for de-duplication.
            if not event_id:
                event_id = self.stable_fallback(title, course_id, due)

            assignments.append({
                "event_id": event_id,
                "course_id": course_id,
                "title": title or "Untitled assignment",
                "url": assignment_url,
                "due": due
            })

        return assignments

    def extract_due(self, event):
        # Prefer timestamp attributes if Bennett/Moodle exposes them.
        for attr in (
            "data-event-timestamp",
            "data-timestart",
            "data-event-timestart",
            "data-event-time"
        ):
            value = event.get(attr)
            if value:
                try:
                    number = float(value)
                    if number > 10_000_000:
                        return number
                except ValueError:
                    pass

        # Try standard datetime/timestamp elements.
        for node in event.select(
            "[data-time-start], [data-timestamp], "
            "[data-datetime], time[datetime]"
        ):
            for attr in (
                "data-time-start",
                "data-timestamp",
                "data-datetime",
                "datetime"
            ):
                value = node.get(attr)
                if value:
                    parsed = self.parse_datetime(value)
                    if parsed is not None:
                        return parsed

        # Some Moodle pages expose the timestamp in the event HTML.
        text = " ".join(event.stripped_strings)
        match = re.search(r"\b(1[0-9]{9}|2[0-9]{9})\b", text)
        if match:
            return float(match.group(1))

        return None

    def parse_datetime(self, value):
        value = value.strip()

        try:
            if value.isdigit():
                number = float(value)
                return number if number > 10_000_000 else None

            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TIMEZONE)

            return dt.timestamp()
        except ValueError:
            return None

    def stable_fallback(self, title, course_id, due):
        import hashlib
        raw = f"{course_id}|{title}|{due}"
        return "fallback-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
