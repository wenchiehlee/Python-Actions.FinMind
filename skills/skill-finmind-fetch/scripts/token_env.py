"""FinMind token resolution and quota-aware rotation."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_ENV_NAMES = (
    "FINMIND_TOKEN", "FINMIND_API_TOKEN", "FINDMIND_GMAIL_TOKEN",
    "FINDMIND_GMAIL_TOKEN1", "FINDMIND_GMAIL_TOKEN2",
    "FINDMIND_GMAIL_TOKEN3", "FINDMIND_GMAIL_TOKEN4", "FINDMIND_GMAIL_TOKEN5",
    "FINDMIND_GMAIL_TOKEN6",
)
QUOTA_URL = "https://api.web.finmindtrade.com/v2/user_info"

def get_finmind_tokens(explicit=None):
    candidates = [explicit] if explicit else [os.getenv(name) for name in TOKEN_ENV_NAMES]
    tokens = []
    for value in candidates:
        if value and value.strip() and value.strip() not in tokens:
            tokens.append(value.strip())
    return tokens

def token_quota(token):
    """Return remaining quota and a state reflecting that quota; never expose account metadata."""
    try:
        payload = requests.get(QUOTA_URL, headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
        limit = int(payload.get("api_request_limit", 0) or 0)
        used = int(payload.get("user_count", 0) or 0)
        if limit <= 0:
            return -1, "quota-unavailable"
        remaining = max(limit - used, 0)
        state = "exhausted" if remaining <= 0 else "ok"
        return remaining, state
    except (requests.RequestException, ValueError, TypeError):
        return -1, "quota-check-failed"

def order_tokens(tokens):
    checked = [(token_quota(token), index, token) for index, token in enumerate(tokens)]
    checked.sort(key=lambda item: (-item[0][0], item[1]))
    return [token for _, _, token in checked], [details for details, _, _ in checked]

class TokenRotator:
    """Rotate across tokens ordered by their current remaining quota."""
    def __init__(self, explicit=None):
        tokens = get_finmind_tokens(explicit)
        self._tokens, self._details = order_tokens(tokens)
        self._index = 0

    @property
    def count(self):
        return len(self._tokens)

    def next(self):
        if not self._tokens:
            return None
        token = self._tokens[self._index]
        self._index = (self._index + 1) % len(self._tokens)
        return token

    def retire(self, token):
        if token in self._tokens:
            self._tokens.remove(token)
            if self._tokens:
                self._index %= len(self._tokens)
            else:
                self._index = 0
