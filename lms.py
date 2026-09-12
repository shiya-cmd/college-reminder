import re
import requests

from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs

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

        # Try previously saved cookies first.
        load_cookies(user_id, self.session)

    # ---------------------------------------------------------
    # LOGIN CHECK
    # ---------------------------------------------------------

    def looks_logged_out(self, response):
        soup = BeautifulSoup(response.text, "html.parser")

        login_form = soup.find("form", id="login")

        if login_form:
            return True

        if "login/index.php" in response.url:
            return True

        return False

    # ---------------------------------------------------------
    # CALENDAR
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # LOGIN
    # ---------------------------------------------------------

    def login(self, username, password):

        try:
            # Open login page first.
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
            else:
                action = urljoin(BASE_URL, action)

            # Collect hidden fields such as logintoken.
            data = {}

            for field in login_form.find_all("input"):

                name = field.get("name")
                value = field.get("value", "")

                if name:
                    data[name] = value

            # Insert credentials.
            data["username"] = username
            data["password"] = password

            response = self.session.post(
                action,
                data=data,
                timeout=20,
                allow_redirects=True
            )

            response.raise_for_status()

            # Check whether Moodle sent us back to login.
            if self.looks_logged_out(response):
                return False, "Invalid LMS username or password."

            # Save cookies after successful login.
            save_cookies(self.user_id, self.session)

            return True, "Login successful."

        except requests.RequestException as e:

            return False, f"LMS connection error: {e}"

    # ---------------------------------------------------------
    # ENSURE LOGIN
    # ---------------------------------------------------------

    def ensure_login(self, username, password):

        # 1. Try existing cookies.
        html = self.calendar()

        if html is not None:
            return True, html, False

        # 2. Cookies expired.
        # Automatically login again using saved credentials.
        ok, message = self.login(username, password)

        if not ok:
            delete_cookies(self.user_id)

            return False, message, True

        # 3. Try calendar again after login.
        html = self.calendar()

        if html is None:

            return (
                False,
                "Calendar unavailable after login.",
                True
            )

        return True, html, True

    # ---------------------------------------------------------
    # SCRAPE ASSIGNMENTS
    # ---------------------------------------------------------

    def scrape_assignments(self, html):

        soup = BeautifulSoup(html, "html.parser")

        assignments = []

        events = soup.select(
            '[data-type="event"][data-event-component="mod_assign"]'
        )

        for event in events:

            # Only assignment "due" events.
            event_type = event.get(
                "data-event-eventtype"
            )

            if event_type != "due":
                continue

            # -------------------------------------------------
            # TITLE
            # -------------------------------------------------

            title = event.get(
                "data-event-title"
            )

            if not title:

                title_element = event.select_one(
                    ".name"
                )

                if title_element:
                    title = title_element.get_text(
                        " ",
                        strip=True
                    )

            # -------------------------------------------------
            # EVENT ID
            # -------------------------------------------------

            event_id = event.get(
                "data-event-id"
            )

            # -------------------------------------------------
            # COURSE ID
            # -------------------------------------------------

            course_id = event.get(
                "data-course-id"
            )

            # -------------------------------------------------
            # COURSE NAME
            # -------------------------------------------------

            course = self.extract_course(event)

            # -------------------------------------------------
            # ASSIGNMENT URL
            # -------------------------------------------------

            link = event.select_one(
                'a[href*="/mod/assign/view.php"]'
            )

            assignment_url = None

            if link:

                assignment_url = link.get("href")

                if assignment_url:
                    assignment_url = urljoin(
                        BASE_URL,
                        assignment_url
                    )

            # -------------------------------------------------
            # DUE TIME
            # -------------------------------------------------

            due = self.extract_due(event)

            # -------------------------------------------------
            # FALLBACK EVENT ID
            # -------------------------------------------------

            if not event_id:

                event_id = self.stable_fallback(
                    title,
                    course_id,
                    due
                )

            assignments.append({

                "event_id": str(event_id),

                "course_id": course_id,

                "course": course,

                "title": (
                    title
                    or "Untitled assignment"
                ),

                "url": assignment_url,

                "due": due
            })

        return assignments

    # ---------------------------------------------------------
    # EXTRACT COURSE NAME
    # ---------------------------------------------------------

    def extract_course(self, event):

        # Bennett's HTML contains:
        #
        # <a href="/course/view.php?id=15833">
        # CSET211: Statistical Machine Learning...
        # </a>

        for link in event.select("a[href]"):

            href = link.get("href", "")

            if "/course/view.php" not in href:
                continue

            text = link.get_text(
                " ",
                strip=True
            )

            if text:
                return text

        # If course name cannot be found,
        # use course ID.
        return (
            event.get("data-course-id")
            or "Bennett LMS"
        )

    # ---------------------------------------------------------
    # EXTRACT DUE TIME
    # ---------------------------------------------------------

    def extract_due(self, event):

        """
        Bennett's actual calendar HTML contains something like:

        <div class="col-11">
            <a href="...calendar/view.php?view=day&time=1790447400">
                Sunday, 27 September
            </a>,
            12:00 AM
        </div>

        The timestamp in the URL identifies the calendar day,
        while the visible text contains the actual displayed
        time.

        Therefore we combine:

            date from timestamp
            +
            time from visible text

        and interpret it in Asia/Kolkata.
        """

        # -----------------------------------------------------
        # 1. Find the "When" row.
        # -----------------------------------------------------

        when_row = None

        for row in event.select(".row"):

            text = row.get_text(
                " ",
                strip=True
            )

            if "12:00" in text or "AM" in text or "PM" in text:

                if row.select_one(
                    'a[href*="calendar/view.php"]'
                ):
                    when_row = row
                    break

        # -----------------------------------------------------
        # 2. Extract calendar day timestamp.
        # -----------------------------------------------------

        day_timestamp = None

        if when_row:

            day_link = when_row.select_one(
                'a[href*="calendar/view.php"]'
            )

            if day_link:

                href = day_link.get(
                    "href",
                    ""
                )

                parsed = urlparse(href)

                query = parse_qs(
                    parsed.query
                )

                timestamp_values = query.get(
                    "time"
                )

                if timestamp_values:

                    try:
                        day_timestamp = float(
                            timestamp_values[0]
                        )

                    except (ValueError, TypeError):
                        day_timestamp = None

        # -----------------------------------------------------
        # 3. Extract displayed date/time.
        # -----------------------------------------------------

        if when_row and day_timestamp:

            row_text = when_row.get_text(
                " ",
                strip=True
            )

            # Example:
            #
            # Sunday, 27 September, 12:00 AM
            #
            match = re.search(
                r"(\d{1,2})\s+"
                r"([A-Za-z]+)"
                r"(?:,)?\s+"
                r"(\d{1,2}:\d{2}\s*(?:AM|PM))",
                row_text,
                re.IGNORECASE
            )

            if match:

                day = int(
                    match.group(1)
                )

                month_name = match.group(2)

                time_text = match.group(3)

                # Determine year from the calendar timestamp.
                calendar_date = datetime.fromtimestamp(
                    day_timestamp,
                    TIMEZONE
                )

                year = calendar_date.year

                try:

                    month = datetime.strptime(
                        month_name,
                        "%B"
                    ).month

                except ValueError:

                    try:

                        month = datetime.strptime(
                            month_name,
                            "%b"
                        ).month

                    except ValueError:

                        month = None

                if month:

                    try:

                        date_text = (
                            f"{day} "
                            f"{month_name} "
                            f"{year} "
                            f"{time_text}"
                        )

                        dt = datetime.strptime(
                            date_text,
                            "%d %B %Y %I:%M %p"
                        )

                        dt = dt.replace(
                            tzinfo=TIMEZONE
                        )

                        return dt.timestamp()

                    except ValueError:

                        try:

                            dt = datetime.strptime(
                                date_text,
                                "%d %b %Y %I:%M %p"
                            )

                            dt = dt.replace(
                                tzinfo=TIMEZONE
                            )

                            return dt.timestamp()

                        except ValueError:
                            pass

        # -----------------------------------------------------
        # 4. Fallback: timestamp attributes.
        # -----------------------------------------------------

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

                except (ValueError, TypeError):
                    pass

        # -----------------------------------------------------
        # 5. Fallback: datetime/timestamp elements.
        # -----------------------------------------------------

        for node in event.select(
            "[data-time-start], "
            "[data-timestamp], "
            "[data-datetime], "
            "time[datetime]"
        ):

            for attr in (
                "data-time-start",
                "data-timestamp",
                "data-datetime",
                "datetime"
            ):

                value = node.get(attr)

                if value:

                    parsed = self.parse_datetime(
                        value
                    )

                    if parsed is not None:
                        return parsed

        return None

    # ---------------------------------------------------------
    # PARSE DATETIME
    # ---------------------------------------------------------

    def parse_datetime(self, value):

        value = value.strip()

        try:

            if value.isdigit():

                number = float(value)

                if number > 10_000_000:
                    return number

                return None

            dt = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00"
                )
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=TIMEZONE
                )

            return dt.timestamp()

        except (ValueError, TypeError):

            return None

    # ---------------------------------------------------------
    # FALLBACK ID
    # ---------------------------------------------------------

    def stable_fallback(
        self,
        title,
        course_id,
        due
    ):

        import hashlib

        raw = (
            f"{course_id}|"
            f"{title}|"
            f"{due}"
        )

        return (
            "fallback-"
            + hashlib.sha256(
                raw.encode()
            ).hexdigest()[:24]
        )