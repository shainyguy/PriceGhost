import ssl
import uuid
import time
import logging
from typing import Optional

import aiohttp
import certifi

from config import config

logger = logging.getLogger(__name__)


class GigaChatAPI:
    """Клиент GigaChat API от Сбера"""

    def __init__(self):
        self.auth_key = config.gigachat.auth_key
        self.scope = config.gigachat.scope
        self.token_url = config.gigachat.token_url
        self.api_url = config.gigachat.api_url
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    async def _get_token(self) -> Optional[str]:
        """Получает / обновляет access token"""
        now = time.time()
        if self._access_token and now < self._token_expires - 60:
            return self._access_token

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self.auth_key}",
        }
        data = {"scope": self.scope}

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        timeout = aiohttp.ClientTimeout(total=15)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.token_url,
                    headers=headers,
                    data=data,
                    ssl=ssl_context,
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        self._access_token = result.get("access_token")
                        self._token_expires = result.get("expires_at", now + 1800) / 1000
                        logger.info("✅ GigaChat token obtained")
                        return self._access_token
                    else:
                        error_text = await resp.text()
                        logger.error(f"GigaChat token error {resp.status}: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"GigaChat token request failed: {e}")
            return None

    async def ask(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> Optional[str]:
        """Отправляет запрос к GigaChat и возвращает ответ"""
        token = await self._get_token()
        if not token:
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.api_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    ssl=ssl_context,
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        choices = result.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
                        return None
                    else:
                        error_text = await resp.text()
                        logger.error(f"GigaChat API error {resp.status}: {error_text}")
                        # Сброс токена при 401
                        if resp.status == 401:
                            self._access_token = None
                        return None
        except Exception as e:
            logger.error(f"GigaChat request failed: {e}")
            return None


# Singleton
_gigachat: Optional[GigaChatAPI] = None


def get_gigachat() -> GigaChatAPI:
    global _gigachat
    if _gigachat is None:
        _gigachat = GigaChatAPI()
    return _gigachat