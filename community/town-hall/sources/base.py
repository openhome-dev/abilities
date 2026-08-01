from abc import ABC, abstractmethod
from typing import Optional
import json


class _SimpleResponse:
    """minimal response wrapper for sdk results that are plain strings."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    @property
    def content(self) -> bytes:
        return (self.text or "").encode("utf-8", errors="ignore")

    def json(self):
        return json.loads(self.text or "{}")


class CivicSource(ABC):
    """base class for all civic data sources (cities, counties, states)."""

    def __init__(self):
        self._api_key: Optional[str] = None
        self._worker = None

    def required_api_key_name(self) -> Optional[str]:
        """override to declare the third-party key name this source needs.
        return None if no api key is required."""
        return None

    def set_api_key(self, api_key: Optional[str]) -> None:
        """called by the capability coordinator after resolving required_api_key_name."""
        self._api_key = api_key.strip() if api_key else None

    def trigger_keywords(self) -> tuple[str, ...]:
        """override to declare which keywords in the trigger phrase activate this source.
        return an empty tuple to always include this source regardless of trigger."""
        return ()

    def validate_cache(self, content: str) -> bool:
        """optional source hook for custom cache rules.
        briefing section parsing lives in main.py (_extract_section)."""
        return True

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def get_source_url(self) -> str:
        pass

    @abstractmethod
    async def fetch_updates(self) -> str:
        pass

    async def fetch_meetings(self) -> str:
        """meetings calendar briefing. sources should override; default uses fetch_updates."""
        return await self.fetch_updates()

    async def search(self, query: str) -> str:
        """search this source for specific items (optional feature)."""
        return f"Live search not yet implemented for {self.get_name()}."

    async def get_details(self, item_id: str) -> str:
        """get detailed information about a specific item (optional feature)."""
        return f"Detail retrieval not yet implemented for {self.get_name()}."

    async def fetch_legislation(self) -> str:
        """fetch pending legislation (optional feature for sources with legislative data)."""
        return f"Legislation tracking not available for {self.get_name()}."

    def set_topic_preferences(self, topics: list[str]) -> None:
        """store user's topic preferences (optional feature for sources with topic filtering)."""
        pass  # sources that support this will override

    def get_topic_preferences(self) -> list[str]:
        """retrieve stored topic preferences (optional feature)."""
        return []  # default: no preferences

    def get_metadata(self) -> dict:
        """return additional metadata about this source (optional)."""
        return {}

    def bind_worker(self, worker):
        """bind the worker for http requests."""
        self._worker = worker

    @staticmethod
    def _normalize_response(response):
        """wrap sdk results so callers can rely on .text/.status_code."""
        if response is None:
            return _SimpleResponse("", status_code=502)

        if isinstance(response, dict):
            text = response.get("text") or response.get("body") or response.get("content") or ""
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
            status = int(response.get("status_code") or response.get("status") or 200)
            return _SimpleResponse(str(text), status_code=status)

        if isinstance(response, (bytes, bytearray)):
            return _SimpleResponse(response.decode("utf-8", errors="ignore"), status_code=200)

        # response-like object from the sdk (duck-typed without getattr)
        try:
            status = int(response.status_code or 200)
            text = response.text
            if text is None:
                content = response.content
                if isinstance(content, bytes):
                    text = content.decode("utf-8", errors="ignore")
                else:
                    text = str(content or "")
            return _SimpleResponse(text or "", status_code=status)
        except Exception:
            pass

        text = response if isinstance(response, str) else str(response)
        lowered = (text or "").lower()
        if (
            not text.strip()
            or text.startswith("coroutine ")
            or text.startswith("<coroutine")
            or "traceback" in lowered
            or lowered.startswith("error")
            or "failed" in lowered[:100]
        ):
            return _SimpleResponse(text, status_code=502)
        return _SimpleResponse(text, status_code=200)

    async def _session_http_get(self, url: str, headers: dict = None, timeout: float = None, params: dict = None):
        """call the best available session_tasks get helper for async methods."""
        st = self._worker.session_tasks
        headers = headers or {}
        kwargs = {"headers": headers}
        if params:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = timeout

        async def _call(method):
            try:
                return await method(url, **kwargs)
            except TypeError:
                # some builds reject timeout/params — retry with headers only
                return await method(url, headers=headers)

        if hasattr(st, "get_async"):
            return await _call(st.get_async)
        if hasattr(st, "httpx_get_async"):
            return await _call(st.httpx_get_async)
        if hasattr(st, "aiohttp_get_async"):
            resp = await _call(st.aiohttp_get_async)
            try:
                text = await resp.text()
            except TypeError:
                return resp
            try:
                status = int(resp.status)
            except Exception:
                try:
                    status = int(resp.status_code)
                except Exception:
                    status = 200
            return _SimpleResponse(text or "", status_code=status)
        # last resort: sync get
        try:
            response = st.get(url, **kwargs)
        except TypeError:
            response = st.get(url, headers=headers)
        try:
            response = await response
        except TypeError:
            pass
        return response

    async def _session_http_post(
        self, url: str, headers: dict = None, json_body: dict = None, timeout: float = None
    ):
        st = self._worker.session_tasks
        headers = headers or {}
        kwargs = {"headers": headers, "json": json_body}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if hasattr(st, "post_async"):
            try:
                return await st.post_async(url, **kwargs)
            except TypeError:
                return await st.post_async(url, headers=headers, json=json_body)
        if hasattr(st, "httpx_post_async"):
            try:
                return await st.httpx_post_async(url, **kwargs)
            except TypeError:
                return await st.httpx_post_async(url, headers=headers, json=json_body)
        try:
            response = st.post(url, **kwargs)
        except TypeError:
            response = st.post(url, headers=headers, json=json_body)
        try:
            response = await response
        except TypeError:
            pass
        return response

    async def _http_get(
        self, url: str, headers: dict = None, timeout: float = None, params: dict = None
    ):
        """http get using openhome session_tasks async helpers."""
        if not self._worker:
            raise RuntimeError("worker not bound - call bind_worker() first")
        try:
            response = await self._session_http_get(
                url, headers=headers, timeout=timeout, params=params
            )
        except Exception as e:
            raise RuntimeError(f"HTTP GET failed for {url}: {e}") from e
        return self._normalize_response(response)

    async def _http_post(self, url: str, headers: dict = None, json_body: dict = None, timeout: float = None):
        """http post using openhome session_tasks async helpers."""
        if not self._worker:
            raise RuntimeError("worker not bound - call bind_worker() first")
        try:
            response = await self._session_http_post(
                url, headers=headers, json_body=json_body, timeout=timeout
            )
        except Exception as e:
            raise RuntimeError(f"HTTP POST failed for {url}: {e}") from e
        return self._normalize_response(response)
