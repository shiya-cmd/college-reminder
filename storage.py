from pathlib import Path
import json
from cryptography.fernet import Fernet
from config import CREDENTIAL_KEY, COOKIE_DIR

def _fernet():
    if not CREDENTIAL_KEY:
        raise RuntimeError("CREDENTIAL_KEY is missing in .env")
    return Fernet(CREDENTIAL_KEY.encode())

def encrypt_password(password):
    return _fernet().encrypt(password.encode()).decode()

def decrypt_password(value):
    return _fernet().decrypt(value.encode()).decode()

def cookie_path(user_id):
    return COOKIE_DIR / f"{user_id}.json"

def save_cookies(user_id, session):
    path = cookie_path(user_id)
    cookies = requests_cookie_dict(session)
    path.write_text(json.dumps(cookies), encoding="utf-8")

def load_cookies(user_id, session):
    path = cookie_path(user_id)
    if not path.exists():
        return False

    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
        session.cookies.update(cookies)
        return True
    except (OSError, json.JSONDecodeError):
        return False

def delete_cookies(user_id):
    path = cookie_path(user_id)
    if path.exists():
        path.unlink()

def requests_cookie_dict(session):
    import requests
    return requests.utils.dict_from_cookiejar(session.cookies)
