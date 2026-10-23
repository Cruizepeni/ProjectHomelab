from __future__ import annotations

import hmac
from typing import Callable

from YouSnipeSettings import get_effective_settings


def authenticate_ai_tool(provided_token: str, access_token: Callable[[str], str]) -> bool:
    if not provided_token or not get_effective_settings()['aiTool']['enabled']:
        return False
    return hmac.compare_digest(provided_token, access_token('aitool'))
