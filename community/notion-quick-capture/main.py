"""
Notion Quick Capture — voice inbox for Notion.
Capture tasks and notes, search, read pages, and query databases by voice.
"""
import json
import re
import time
from datetime import datetime, timedelta

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# Replace with your Notion integration token before uploading.
# Get one at notion.so/profile/integrations — starts with ntn_
NOTION_INTEGRATION_TOKEN = "REPLACE_WITH_YOUR_KEY"

PREFS_FILE = "notion_capture_prefs.json"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
SCHEMA_CACHE_TTL = 30 * 60
MAX_SPOKEN_ITEMS = 4
EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye",
    "never mind", "no thanks", "that's all", "that is all",
    "i'm done", "that's it", "i'm good", "we're done",
    "all set", "nothing else", "all done", "i'm finished",
}

VOICE_FORMAT_INSTRUCTION = (
    "Use plain spoken English only. No markdown, no bullet points, "
    "no numbered lists, no emoji, no URLs, no special formatting."
)


def _strip_json_fences(raw):
    if not raw or not isinstance(raw, str):
        return raw or ""
    raw = raw.strip()
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _is_exit(text):
    if not text:
        return False
    lower = text.lower().strip()
    for w in EXIT_WORDS:
        if lower == w or lower.startswith(w + " ") or lower.endswith(" " + w):
            return True
    return False


class NotionQuickCaptureCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Logging helpers
    # -------------------------------------------------------------------------

    def _log_info(self, msg):
        self.worker.editor_logging_handler.info(
            f"[NotionCapture] {msg}"
        )

    def _log_warn(self, msg):
        self.worker.editor_logging_handler.warning(
            f"[NotionCapture] {msg}"
        )

    def _log_err(self, msg):
        self.worker.editor_logging_handler.error(
            f"[NotionCapture] {msg}"
        )

    def _is_invalid_token_response(self, response):
        if not response:
            return False
        if response.status_code == 401:
            return True
        try:
            body = response.json() if response.text else {}
        except Exception:
            body = {}
        code = str(body.get("code", "")).lower()
        msg = str(body.get("message", "")).lower()
        return (
            code in {"unauthorized", "invalid_api_key"}
            or ("token" in msg and "invalid" in msg)
        )

    # -------------------------------------------------------------------------
    # Prefs (delete-then-write JSON)
    # -------------------------------------------------------------------------

    async def _load_prefs(self):
        default = {
            "integration_token": None,
            "databases": [],
            "notes_page_id": None,
            "timezone": self.capability_worker.get_timezone() or "America/Los_Angeles",
        }
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            raw = await self.capability_worker.read_file(PREFS_FILE, False)
            try:
                default.update(json.loads(raw))
            except Exception as e:
                self._log_warn(f"Prefs parse error: {e}")
        preset = (NOTION_INTEGRATION_TOKEN or "").strip()
        if preset.startswith("ntn_"):
            default["integration_token"] = preset
        token = (default.get("integration_token") or "").strip()
        if not token or not token.startswith("ntn_"):
            default["integration_token"] = None
        return default

    async def _save_prefs(self, prefs):
        if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(
            PREFS_FILE, json.dumps(prefs), False
        )

    # -------------------------------------------------------------------------
    # Notion API helpers
    # -------------------------------------------------------------------------

    def _headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def _validate_token(self, token):
        try:
            r = requests.get(
                f"{NOTION_BASE}/users/me",
                headers=self._headers(token),
                timeout=10,
            )
            return r.status_code == 200
        except Exception as e:
            self._log_err(f"Token validation: {e}")
            return False

    def _extract_titles(self, results):
        titles = []
        for res in results:
            title = "Untitled"
            for pval in res.get("properties", {}).values():
                if pval.get("type") == "title":
                    parts = pval.get("title", [])
                    t = " ".join(
                        p.get("plain_text", "") for p in parts
                    ).strip()
                    if t:
                        title = t
                    break
            titles.append(title)
        return titles

    # -------------------------------------------------------------------------
    # Command classification (LLM with heuristic fallback)
    # -------------------------------------------------------------------------

    def _classify_command(self, user_text):
        prompt = (
            "Classify this Notion voice command.\n"
            "Return ONLY valid JSON. No markdown fences.\n\n"
            "{\n"
            '  "mode": "quick_add | quick_note | search '
            '| read_page | query_database",\n'
            '  "target_db": <string or null>,\n'
            '  "content": <string or null>,\n'
            '  "search_query": <string or null>\n'
            "}\n\n"
            "Examples:\n"
            "  'add to my tasks review the PR by Friday'\n"
            '    -> {"mode":"quick_add","target_db":"tasks",'
            '"content":"review the PR by Friday"}\n'
            "  'add a note the client wants blue'\n"
            '    -> {"mode":"quick_note","content":'
            '"the client wants blue"}\n'
            "  'what tasks are due this week'\n"
            '    -> {"mode":"query_database","target_db":"tasks",'
            '"content":"due this week"}\n'
            "  'find my notes about marketing'\n"
            '    -> {"mode":"search","search_query":"marketing"}\n'
            "  'read me the onboarding doc'\n"
            '    -> {"mode":"read_page","search_query":"onboarding"}\n'
            f'\nUser said: "{user_text}"'
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        raw = _strip_json_fences(raw)
        try:
            out = json.loads(raw)
            mode = (out.get("mode") or "quick_note").strip().lower()
            valid = {
                "quick_add", "quick_note", "search",
                "read_page", "query_database",
            }
            if mode not in valid:
                mode = "quick_note"
            return {
                "mode": mode,
                "target_db": out.get("target_db"),
                "content": out.get("content"),
                "search_query": out.get("search_query"),
            }
        except Exception as e:
            self._log_warn(f"Classify parse: {e}")

        lower = user_text.lower()
        if any(w in lower for w in ("add", "new", "create", "capture")):
            if any(w in lower for w in ("note", "notes")):
                return {
                    "mode": "quick_note", "target_db": None,
                    "content": user_text, "search_query": None,
                }
            return {
                "mode": "quick_add", "target_db": "tasks",
                "content": user_text, "search_query": None,
            }
        if any(w in lower for w in ("search", "find")):
            return {
                "mode": "search", "target_db": None,
                "content": None, "search_query": user_text,
            }
        if any(w in lower for w in ("read", "summarize")):
            return {
                "mode": "read_page", "target_db": None,
                "content": None, "search_query": user_text,
            }
        if any(w in lower for w in (
            "what", "show", "list", "query", "due", "overdue",
        )):
            return {
                "mode": "query_database", "target_db": "tasks",
                "content": user_text, "search_query": None,
            }
        return {
            "mode": "quick_note", "target_db": None,
            "content": user_text, "search_query": None,
        }

    def _get_db_by_nickname(self, prefs, nickname):
        nickname_lower = (nickname or "").strip().lower()
        for db in prefs.get("databases", []):
            if (db.get("nickname") or "").lower() == nickname_lower:
                return db
        dbs = prefs.get("databases", [])
        return dbs[0] if dbs else None

    # -------------------------------------------------------------------------
    # Schema cache
    # -------------------------------------------------------------------------

    def _is_db_compatible(self, token, db_id):
        """Check if a database is supported by the API version."""
        try:
            r = requests.get(
                f"{NOTION_BASE}/databases/{db_id}",
                headers=self._headers(token),
                timeout=10,
            )
            if r.status_code == 200:
                return True
            if r.status_code == 400:
                body = r.json() if r.text else {}
                msg = body.get("message", "")
                if "multiple data sources" in msg.lower():
                    return False
            return r.status_code != 404
        except Exception:
            return True

    async def _get_schema(self, prefs, db_config):
        db_id = db_config.get("database_id")
        if not db_id:
            return {}
        db_config["last_schema_auth_error"] = False
        cache = db_config.get("schema_cache") or {}
        cached_at = db_config.get("schema_cached_at") or 0
        if cache and time.time() - cached_at < SCHEMA_CACHE_TTL:
            return cache
        try:
            r = requests.get(
                f"{NOTION_BASE}/databases/{db_id}",
                headers=self._headers(prefs["integration_token"]),
                timeout=10,
            )
            if r.status_code == 400:
                body = r.json() if r.text else {}
                msg = body.get("message", "")
                if "multiple data sources" in msg.lower():
                    self._log_warn(
                        f"Database {db_id} uses multiple "
                        "data sources — not supported"
                    )
                    db_config["unsupported"] = True
                return cache
            if self._is_invalid_token_response(r):
                db_config["last_schema_auth_error"] = True
                self._log_warn(
                    "Schema fetch unauthorized — integration token "
                    "is invalid or expired"
                )
                return cache
            if r.status_code != 200:
                return cache
            props = r.json().get("properties", {})
            schema = {
                name: info["type"]
                for name, info in props.items()
            }
            db_config["schema_cache"] = schema
            db_config["schema_cached_at"] = time.time()
            title_prop = next(
                (n for n, info in props.items()
                 if info.get("type") == "title"), None,
            )
            if title_prop:
                db_config["title_property"] = title_prop
            return schema
        except Exception as e:
            self._log_warn(f"Schema fetch: {e}")
            return cache

    # -------------------------------------------------------------------------
    # First-run setup
    # -------------------------------------------------------------------------

    async def _first_run_setup(self, prefs):
        token = (prefs.get("integration_token") or "").strip()

        if not token or not token.startswith("ntn_"):
            await self.capability_worker.speak(
                "To connect Notion, I need your integration token."
            )
            await self.capability_worker.speak(
                "Go to notion dot S O slash profile slash integrations. "
                "Click New Integration. Name it OpenHome and select "
                "your workspace."
            )
            await self.capability_worker.speak(
                "Use the default permissions, those will work. "
                "Copy the token, it starts with N T N "
                "underscore, and read it to me."
            )
            token_input = await self.capability_worker.user_response()
            if not token_input or not token_input.strip().startswith("ntn_"):
                await self.capability_worker.speak(
                    "That doesn't look like a valid Notion token. "
                    "It should start with N T N underscore. "
                    "Try again later."
                )
                return False
            token = token_input.strip()

        if not self._validate_token(token):
            await self.capability_worker.speak(
                "That Notion token didn't work. Make sure you copied "
                "the full token starting with N T N underscore."
            )
            return False

        prefs["integration_token"] = token

        await self.capability_worker.speak(
            "Connected! Now share your databases and pages with "
            "the integration."
        )
        await self.capability_worker.speak(
            "In Notion, open each database or page you want me to "
            "access. Click the three-dot menu, select Add connections, "
            "and find OpenHome."
        )
        await self.capability_worker.run_io_loop(
            "Say done when you're ready."
        )

        try:
            r = requests.post(
                f"{NOTION_BASE}/search",
                headers=self._headers(token),
                json={
                    "filter": {
                        "property": "object", "value": "database",
                    },
                    "page_size": 10,
                },
                timeout=10,
            )
            if r.status_code != 200 or not r.json().get("results"):
                await self.capability_worker.speak(
                    "I don't see any databases shared with me. "
                    "Share at least one database in Notion, then "
                    "try again."
                )
                await self._save_prefs(prefs)
                return True

            results = r.json()["results"]
            databases = []
            names = []
            skipped = []
            for db_obj in results[:6]:
                if len(databases) >= 3:
                    break
                db_id = db_obj.get("id")
                title_parts = db_obj.get("title", [])
                title = " ".join(
                    t.get("plain_text", "") for t in title_parts
                ).strip() or "Database"
                if not self._is_db_compatible(token, db_id):
                    skipped.append(title)
                    self._log_warn(
                        f"Skipping '{title}' — uses "
                        "multiple data sources"
                    )
                    continue
                nickname = re.sub(
                    r"[^a-z0-9 ]", "", title.lower()
                ).strip().replace(" ", "_")[:20] or "database"
                databases.append({
                    "nickname": nickname,
                    "database_id": db_id,
                    "title_property": None,
                    "schema_cache": {},
                    "schema_cached_at": 0,
                })
                names.append(title)
            prefs["databases"] = databases

            if not databases:
                skip_names = ", ".join(skipped) if skipped else ""
                msg = (
                    "None of the shared databases are compatible "
                    "with the current Notion API."
                )
                if skip_names:
                    msg += (
                        f" I had to skip {skip_names} because "
                        "they use multiple data sources."
                    )
                msg += (
                    " Try sharing a standard database instead."
                )
                await self.capability_worker.speak(msg)
                await self._save_prefs(prefs)
                return True

            joined = ", ".join(names)
            await self.capability_worker.speak(
                f"I found {len(databases)} compatible "
                f"database{'s' if len(databases) != 1 else ''}: "
                f"{joined}."
            )

            if skipped:
                skip_joined = ", ".join(skipped)
                await self.capability_worker.speak(
                    f"I skipped {skip_joined} because "
                    "they use multiple data sources, which "
                    "the Notion API doesn't support yet."
                )

            nick_list = ", ".join(
                db["nickname"].replace("_", " ")
                for db in databases
            )
            await self.capability_worker.speak(
                f"You can refer to them as: {nick_list}. "
                "I'll use the first one as your default."
            )
        except Exception as e:
            self._log_err(f"Setup database search: {e}")
            await self.capability_worker.speak(
                "Something went wrong finding your databases. "
                "Try again later."
            )

        await self.capability_worker.speak(
            "Do you have a page for quick notes? If so, tell me "
            "its name. Otherwise say skip."
        )
        notes_reply = await self.capability_worker.user_response()
        if notes_reply and not any(
            w in (notes_reply or "").lower()
            for w in ("skip", "no", "nah", "nope", "pass", "don't have")
        ):
            try:
                rn = requests.post(
                    f"{NOTION_BASE}/search",
                    headers=self._headers(token),
                    json={
                        "query": notes_reply.strip()[:80],
                        "page_size": 3,
                        "filter": {
                            "property": "object", "value": "page",
                        },
                    },
                    timeout=10,
                )
                if rn.status_code == 200 and rn.json().get("results"):
                    prefs["notes_page_id"] = (
                        rn.json()["results"][0]["id"]
                    )
                    await self.capability_worker.speak(
                        "Got it. Quick notes will go there."
                    )
                else:
                    await self.capability_worker.speak(
                        "I couldn't find that page. Make sure it's "
                        "shared with OpenHome. You can set it up later."
                    )
            except Exception:
                await self.capability_worker.speak(
                    "Couldn't search for that page right now."
                )

        await self._save_prefs(prefs)
        await self.capability_worker.speak("Setup complete!")
        return True

    # -------------------------------------------------------------------------
    # Quick Add (database)
    # -------------------------------------------------------------------------

    async def _quick_add(self, prefs, content, target_db):
        db_config = self._get_db_by_nickname(
            prefs, target_db or "tasks"
        )
        if not db_config:
            await self.capability_worker.speak(
                "No database configured. Run Notion setup first."
            )
            return

        if db_config.get("unsupported"):
            await self.capability_worker.speak(
                "That database uses multiple data sources, "
                "which the Notion API doesn't support yet. "
                "Try a different database."
            )
            return

        schema = await self._get_schema(prefs, db_config)

        title_prop_name = db_config.get("title_property") or next(
            (n for n, t in schema.items() if t == "title"),
            "Name",
        )

        if schema:
            today = datetime.now()
            today_iso = today.strftime("%Y-%m-%d")
            days_to_sunday = 6 - today.weekday()
            end_of_week = (
                today + timedelta(days=days_to_sunday)
            ).strftime("%Y-%m-%d")

            prompt = (
                "Parse this voice input into Notion page "
                "properties.\n"
                "Return ONLY valid JSON. No markdown fences.\n\n"
                f'Voice input: "{content}"\n'
                f"Database properties: {json.dumps(schema)}\n"
                f"Today's date: {today_iso}\n"
                f"End of this week (Sunday): {end_of_week}\n\n"
                "{\n"
                '  "title": "<string - the main item name>",\n'
                '  "properties": {}\n'
                "}\n\n"
                "Only include properties that exist in the schema "
                "and were mentioned or can be inferred.\n"
                "Date format: YYYY-MM-DD. Resolve relative dates "
                "(Friday, tomorrow, next week, etc).\n"
                "Examples:\n"
                "  'review the PR by Friday' -> "
                '{"title":"Review the PR",'
                f'"properties":{{"Due Date":"{end_of_week}"}}}}\n'
                "  'call vendor about shipment' -> "
                '{"title":"Call vendor about shipment",'
                '"properties":{}}\n'
                "  'bug login broken high priority' -> "
                '{"title":"Login button broken",'
                '"properties":{"Priority":"High"}}'
            )
            raw = self.capability_worker.text_to_text_response(
                prompt
            )
            raw = _strip_json_fences(raw)
            try:
                parsed = json.loads(raw)
            except Exception as e:
                self._log_warn(f"Quick add parse: {e}")
                parsed = {"title": content[:200], "properties": {}}
        else:
            if db_config.get("last_schema_auth_error"):
                self._log_warn(
                    "Schema unavailable due to token auth error; "
                    "creating with title only"
                )
            else:
                self._log_warn(
                    "Schema empty — creating with title only"
                )
            parsed = {"title": content[:200], "properties": {}}

        title = (
            parsed.get("title") or content or "Untitled"
        )[:200]

        page_props = {
            title_prop_name: {
                "title": [{"text": {"content": title}}]
            }
        }

        if schema:
            for prop_name, value in (
                parsed.get("properties") or {}
            ).items():
                if prop_name not in schema:
                    continue
                ptype = schema[prop_name]
                if ptype == "date":
                    page_props[prop_name] = {
                        "date": {"start": str(value)[:10]}
                    }
                elif ptype == "select":
                    page_props[prop_name] = {
                        "select": {"name": str(value)}
                    }
                elif ptype == "multi_select":
                    vals = (
                        value if isinstance(value, list)
                        else [value]
                    )
                    page_props[prop_name] = {
                        "multi_select": [
                            {"name": str(n)} for n in vals
                        ]
                    }
                elif ptype == "checkbox":
                    page_props[prop_name] = {
                        "checkbox": bool(value)
                    }
                elif ptype == "rich_text":
                    page_props[prop_name] = {
                        "rich_text": [
                            {"text": {
                                "content": str(value)[:2000]
                            }}
                        ]
                    }

        token = prefs["integration_token"]
        db_id = db_config["database_id"]
        db_nick = (target_db or db_config.get("nickname") or "tasks")

        try:
            r = requests.post(
                f"{NOTION_BASE}/pages",
                headers=self._headers(token),
                json={
                    "parent": {"database_id": db_id},
                    "properties": page_props,
                },
                timeout=10,
            )
            if r.status_code == 200:
                extra = ""
                for pn, pv in (
                    parsed.get("properties") or {}
                ).items():
                    if schema.get(pn) == "date":
                        extra = f", due {pv}"
                        break
                await self.capability_worker.speak(
                    f"Added '{title}' to your "
                    f"{db_nick.replace('_', ' ')}{extra}."
                )
            elif self._is_invalid_token_response(r):
                await self.capability_worker.speak(
                    "Your Notion integration token is invalid. "
                    "Please run setup again and paste a new token."
                )
            elif r.status_code == 404:
                await self.capability_worker.speak(
                    "I can't access that database. Make sure it's "
                    "shared with the OpenHome integration."
                )
            elif r.status_code == 429:
                await self.capability_worker.speak(
                    "Notion is asking me to slow down. "
                    "Give me a moment."
                )
            else:
                self._log_err(
                    f"Create page {r.status_code}: "
                    f"{r.text[:300]}"
                )
                fallback_props = {
                    title_prop_name: {
                        "title": [{"text": {"content": title}}]
                    }
                }
                try:
                    r2 = requests.post(
                        f"{NOTION_BASE}/pages",
                        headers=self._headers(token),
                        json={
                            "parent": {"database_id": db_id},
                            "properties": fallback_props,
                        },
                        timeout=10,
                    )
                    if r2.status_code == 200:
                        await self.capability_worker.speak(
                            f"Added '{title}' to your "
                            f"{db_nick.replace('_', ' ')}. "
                            "Some properties didn't match so "
                            "I just added the title."
                        )
                    else:
                        await self.capability_worker.speak(
                            "I couldn't add that. The database "
                            "properties might not match."
                        )
                except Exception:
                    await self.capability_worker.speak(
                        "I couldn't add that. Try again."
                    )
        except requests.exceptions.Timeout:
            await self.capability_worker.speak(
                "Notion didn't respond in time. Try again."
            )
        except Exception as e:
            self._log_err(f"Quick add: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )

    # -------------------------------------------------------------------------
    # Quick Note (page)
    # -------------------------------------------------------------------------

    async def _quick_note(self, prefs, content):
        notes_page_id = prefs.get("notes_page_id")
        if not notes_page_id:
            await self.capability_worker.speak(
                "You don't have a notes page set up. Create a page "
                "in Notion for voice notes, share it with OpenHome, "
                "and run setup again."
            )
            return

        prompt = (
            "Parse this voice note into a title and body.\n"
            "Return ONLY valid JSON. No markdown fences.\n\n"
            f'Voice input: "{content}"\n\n'
            "{\n"
            '  "title": "<short descriptive title, 3-8 words>",\n'
            '  "body": "<the full note content>"\n'
            "}\n\n"
            "The title should capture the topic.\n"
            "Example: 'the client wants blue not green'\n"
            '  -> {"title":"Client color preference",'
            '"body":"The client wants the blue color scheme, '
            'not green."}'
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        raw = _strip_json_fences(raw)
        try:
            parsed = json.loads(raw)
            title = (parsed.get("title") or content[:50])[:200]
            body = (parsed.get("body") or content)[:2000]
        except Exception:
            title = content[:50] if len(content) > 50 else content
            body = content

        try:
            r = requests.post(
                f"{NOTION_BASE}/pages",
                headers=self._headers(prefs["integration_token"]),
                json={
                    "parent": {"page_id": notes_page_id},
                    "properties": {
                        "title": [{"text": {"content": title}}]
                    },
                    "children": [{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": body},
                            }]
                        },
                    }],
                },
                timeout=10,
            )
            if r.status_code == 200:
                await self.capability_worker.speak(
                    f"Noted — saved '{title}' to your notes."
                )
            elif r.status_code == 404:
                await self.capability_worker.speak(
                    "I can't access that notes page. Make sure "
                    "it's shared with the OpenHome integration."
                )
            elif r.status_code == 429:
                await self.capability_worker.speak(
                    "Notion is asking me to slow down. "
                    "Give me a moment."
                )
            else:
                await self.capability_worker.speak(
                    "I couldn't save that note. Try again."
                )
        except requests.exceptions.Timeout:
            await self.capability_worker.speak(
                "Notion didn't respond in time. Try again."
            )
        except Exception as e:
            self._log_err(f"Quick note: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    async def _search(self, prefs, raw_query):
        if not raw_query or not raw_query.strip():
            await self.capability_worker.speak(
                "What would you like me to search for in Notion?"
            )
            return

        extract_prompt = (
            "Extract search keywords from this voice command.\n"
            "Return ONLY JSON. No markdown fences.\n\n"
            '{"query": "<2-5 word search term>"}\n\n'
            "Examples:\n"
            "  'find my notes about marketing' -> "
            '{"query":"marketing"}\n'
            "  'search Notion for Series A' -> "
            '{"query":"Series A"}\n'
            "  'do I have anything about onboarding' -> "
            '{"query":"onboarding"}\n\n'
            f'User said: "{raw_query}"'
        )
        raw = self.capability_worker.text_to_text_response(
            extract_prompt
        )
        raw = _strip_json_fences(raw)
        try:
            search_term = json.loads(raw).get("query", raw_query)
        except Exception:
            search_term = raw_query

        await self.capability_worker.speak("Searching now.")

        try:
            r = requests.post(
                f"{NOTION_BASE}/search",
                headers=self._headers(prefs["integration_token"]),
                json={
                    "query": str(search_term).strip()[:100],
                    "page_size": 5,
                    "filter": {
                        "property": "object", "value": "page",
                    },
                },
                timeout=10,
            )
            if r.status_code == 429:
                await self.capability_worker.speak(
                    "Notion is asking me to slow down. "
                    "Give me a moment."
                )
                return
            if r.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't search Notion right now. "
                    "Try again later."
                )
                return
            results = r.json().get("results", [])
            if not results:
                await self.capability_worker.speak(
                    "I didn't find anything matching that. "
                    "Make sure the page is shared with the "
                    "OpenHome integration, or try different "
                    "keywords."
                )
                return

            titles = self._extract_titles(results)
            joined = ", ".join(titles[:5])
            count = len(titles)
            await self.capability_worker.speak(
                f"I found {count} "
                f"page{'s' if count != 1 else ''} "
                f"matching '{search_term}': {joined}."
            )
            await self.capability_worker.speak(
                "Want me to read any of these?"
            )
        except requests.exceptions.Timeout:
            await self.capability_worker.speak(
                "Notion didn't respond in time. Try again."
            )
        except Exception as e:
            self._log_err(f"Search: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )

    # -------------------------------------------------------------------------
    # Read Page
    # -------------------------------------------------------------------------

    async def _read_page(self, prefs, raw_query):
        if not raw_query or not raw_query.strip():
            await self.capability_worker.speak(
                "Which page would you like me to read?"
            )
            return

        await self.capability_worker.speak("Let me find that.")

        try:
            r = requests.post(
                f"{NOTION_BASE}/search",
                headers=self._headers(prefs["integration_token"]),
                json={
                    "query": str(raw_query).strip()[:100],
                    "page_size": 5,
                    "filter": {
                        "property": "object", "value": "page",
                    },
                },
                timeout=10,
            )
            if (
                r.status_code != 200
                or not r.json().get("results")
            ):
                await self.capability_worker.speak(
                    "I didn't find a page matching that. "
                    "Make sure it's shared with the "
                    "OpenHome integration."
                )
                return

            page_id = r.json()["results"][0]["id"]

            r2 = requests.get(
                f"{NOTION_BASE}/blocks/{page_id}/children",
                headers=self._headers(prefs["integration_token"]),
                params={"page_size": 100},
                timeout=10,
            )
            if r2.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't read that page. Try again later."
                )
                return

            blocks = r2.json().get("results", [])
            text_parts = []
            for block in blocks:
                btype = block.get("type")
                if btype in (
                    "paragraph", "heading_1", "heading_2",
                    "heading_3", "bulleted_list_item",
                    "numbered_list_item", "to_do",
                ):
                    rich = block.get(btype, {}).get(
                        "rich_text", []
                    )
                    text = " ".join(
                        t.get("plain_text", "") for t in rich
                    )
                    if text:
                        text_parts.append(text)
                elif btype == "image":
                    text_parts.append("There is an image here.")
                elif btype == "code":
                    text_parts.append("There is a code block here.")

            if not text_parts:
                await self.capability_worker.speak(
                    "That page exists but it's empty — "
                    "no content to read."
                )
                return

            page_text = "\n".join(text_parts)
            truncated = " ".join(page_text.split()[:3000])

            summary = self.capability_worker.text_to_text_response(
                prompt_text=(
                    "Summarize this Notion page content for "
                    "voice output. Be concise, 2-3 sentences. "
                    "Focus on the key points.\n\n"
                    f"{truncated}"
                ),
                system_prompt=(
                    "You summarize Notion page content into "
                    "brief spoken summaries. Be conversational. "
                    "No bullet points or lists — this is spoken. "
                    "If the page is a task list, mention the "
                    "count and highlight key items. "
                    + VOICE_FORMAT_INSTRUCTION
                ),
            )
            await self.capability_worker.speak(summary)

        except requests.exceptions.Timeout:
            await self.capability_worker.speak(
                "Notion didn't respond in time. Try again."
            )
        except Exception as e:
            self._log_err(f"Read page: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )

    # -------------------------------------------------------------------------
    # Query Database
    # -------------------------------------------------------------------------

    async def _query_database(self, prefs, target_db, content):
        db_config = self._get_db_by_nickname(
            prefs, target_db or "tasks"
        )
        if not db_config:
            await self.capability_worker.speak(
                "No database configured. Run Notion setup first."
            )
            return

        if db_config.get("unsupported"):
            await self.capability_worker.speak(
                "That database uses multiple data sources, "
                "which the Notion API doesn't support yet. "
                "Try a different database."
            )
            return

        schema = await self._get_schema(prefs, db_config)

        query_body = {"page_size": 10}
        if schema:
            today = datetime.now()
            today_iso = today.strftime("%Y-%m-%d")
            days_to_sunday = 6 - today.weekday()
            end_of_week = (
                today + timedelta(days=days_to_sunday)
            ).strftime("%Y-%m-%d")

            prompt = (
                "Build a Notion API database query filter.\n"
                "Return ONLY valid JSON. No markdown fences.\n\n"
                f'User asked: "{content or "list items"}"\n'
                f"Database schema: {json.dumps(schema)}\n"
                f"Today: {today_iso}\n"
                f"End of this week (Sunday): {end_of_week}\n\n"
                "{\n"
                '  "filter": <Notion filter object or null>,\n'
                '  "sorts": [<Notion sort objects>]\n'
                "}\n\n"
                "Filter syntax:\n"
                '  Date: {"property":"P","date":'
                '{"on_or_before":"YYYY-MM-DD"}}\n'
                '  Select: {"property":"P","select":'
                '{"equals":"Value"}}\n'
                '  Status: {"property":"P","status":'
                '{"equals":"Value"}}\n'
                '  Checkbox: {"property":"P","checkbox":'
                '{"equals":true}}\n'
                '  Compound: {"and":[...]} or {"or":[...]}\n\n'
                'If no filter needed, use "filter": null.\n'
                "Sort by most relevant property ascending."
            )
            raw = self.capability_worker.text_to_text_response(
                prompt
            )
            raw = _strip_json_fences(raw)
            try:
                parsed = json.loads(raw)
                if parsed.get("filter"):
                    query_body["filter"] = parsed["filter"]
                if parsed.get("sorts"):
                    query_body["sorts"] = parsed["sorts"]
            except Exception:
                query_body = {"page_size": 10}

        try:
            r = requests.post(
                f"{NOTION_BASE}/databases/"
                f"{db_config['database_id']}/query",
                headers=self._headers(prefs["integration_token"]),
                json=query_body,
                timeout=10,
            )
            if r.status_code == 429:
                await self.capability_worker.speak(
                    "Notion is asking me to slow down. "
                    "Give me a moment."
                )
                return
            if r.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't query that database. Make sure "
                    "it's shared with the OpenHome integration."
                )
                return

            pages = r.json().get("results", [])
            if not pages:
                await self.capability_worker.speak(
                    "No items match that. Your database might "
                    "be empty or the filter didn't match."
                )
                return

            items = []
            for page in pages[:MAX_SPOKEN_ITEMS]:
                item = {}
                for pname, pval in page.get(
                    "properties", {}
                ).items():
                    ptype = pval.get("type")
                    if ptype == "title":
                        item["title"] = " ".join(
                            t.get("plain_text", "")
                            for t in pval.get("title", [])
                        ).strip() or "Untitled"
                    elif ptype == "date" and pval.get("date"):
                        item[pname] = (
                            pval["date"].get("start", "")
                        )
                    elif ptype == "select" and pval.get("select"):
                        item[pname] = (
                            pval["select"].get("name", "")
                        )
                    elif ptype == "status" and pval.get("status"):
                        item[pname] = (
                            pval["status"].get("name", "")
                        )
                items.append(item)

            spoken = self.capability_worker.text_to_text_response(
                f"Turn these database results into a brief "
                f"spoken summary for voice output. Lead with "
                f"the total count, then highlight the most "
                f"important items. Keep it to 3-5 sentences "
                f"total. {VOICE_FORMAT_INSTRUCTION}\n\n"
                f"{json.dumps(items)}"
            )
            await self.capability_worker.speak(spoken)

            if len(pages) > MAX_SPOKEN_ITEMS:
                await self.capability_worker.speak(
                    f"Plus {len(pages) - MAX_SPOKEN_ITEMS} more. "
                    "Want me to continue?"
                )
        except requests.exceptions.Timeout:
            await self.capability_worker.speak(
                "Notion didn't respond in time. Try again."
            )
        except Exception as e:
            self._log_err(f"Query DB: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )

    # -------------------------------------------------------------------------
    # Process a single user command
    # -------------------------------------------------------------------------

    async def _process_command(self, prefs, user_input):
        self._log_info(f"Processing: {user_input}")
        classified = self._classify_command(user_input)
        mode = classified.get("mode", "quick_note")
        content = classified.get("content") or ""
        target_db = classified.get("target_db")
        search_query = classified.get("search_query") or content

        self._log_info(
            f"Mode={mode} DB={target_db} "
            f"Content={content[:80]}"
        )

        if mode == "quick_add":
            await self.capability_worker.speak("On it.")
            await self._quick_add(prefs, content, target_db)
        elif mode == "quick_note":
            await self.capability_worker.speak("Got it.")
            await self._quick_note(prefs, content)
        elif mode == "search":
            await self._search(prefs, search_query)
        elif mode == "read_page":
            await self._read_page(prefs, search_query)
        elif mode == "query_database":
            await self.capability_worker.speak("One sec.")
            await self._query_database(
                prefs, target_db, content,
            )
        else:
            await self.capability_worker.speak(
                "I'm not sure what you want. Try 'add to my "
                "tasks', 'search Notion', or 'what tasks are "
                "due this week'."
            )

    def _has_actionable_content(self, text):
        if not text:
            return False
        lower = text.lower().strip().strip(".,!?")
        wake_only = {"notion", "hey notion", "open notion"}
        if lower in wake_only:
            return False
        if len(lower.split()) <= 2:
            return False
        return True

    # -------------------------------------------------------------------------
    # Main run loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            prefs = await self._load_prefs()
            token = (prefs.get("integration_token") or "").strip()

            if not token or not token.startswith("ntn_"):
                success = await self._first_run_setup(prefs)
                if not success:
                    return
                prefs = await self._load_prefs()
                token = (
                    prefs.get("integration_token") or ""
                ).strip()
                if not token or not token.startswith("ntn_"):
                    await self.capability_worker.speak(
                        "Notion isn't connected. "
                        "Try again with a valid token."
                    )
                    return

            if not self._validate_token(token):
                self._log_warn("Stored token is invalid")
                prefs["integration_token"] = None
                prefs["databases"] = []
                await self._save_prefs(prefs)
                await self.capability_worker.speak(
                    "Your Notion token is no longer valid. "
                    "Let's set up a new one."
                )
                success = await self._first_run_setup(prefs)
                if not success:
                    return
                prefs = await self._load_prefs()

            if prefs.get("databases"):
                token = prefs["integration_token"]
                valid_dbs = [
                    db for db in prefs["databases"]
                    if self._is_db_compatible(
                        token, db["database_id"]
                    )
                ]
                if len(valid_dbs) < len(prefs["databases"]):
                    removed = len(prefs["databases"]) - len(valid_dbs)
                    prefs["databases"] = valid_dbs
                    await self._save_prefs(prefs)
                    self._log_warn(
                        f"Removed {removed} incompatible "
                        "database(s) from prefs"
                    )
                    if not valid_dbs:
                        await self.capability_worker.speak(
                            "Your saved databases aren't "
                            "compatible with the Notion API. "
                            "They may have been changed to use "
                            "multiple data sources. Share new "
                            "databases and run setup again."
                        )
                        return

            await self.capability_worker.speak(
                "Notion is ready. What would you like to do?"
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input:
                    continue

                if _is_exit(user_input):
                    await self.capability_worker.speak("See you later.")
                    break

                lower = user_input.lower()

                if "setup" in lower or "reconfigure" in lower or "reconnect" in lower:
                    await self._first_run_setup(prefs)
                    prefs = await self._load_prefs()
                    continue

                if "change" in lower and "database" in lower:
                    await self.capability_worker.speak(
                        "Run setup again and I'll re-scan "
                        "your databases."
                    )
                    continue

                if "set" in lower and "notes" in lower and "page" in lower:
                    await self.capability_worker.speak(
                        "What's the name of the page you want "
                        "to use for notes?"
                    )
                    notes_reply = await self.capability_worker.user_response()
                    if notes_reply and not any(
                        w in (notes_reply or "").lower()
                        for w in ("skip", "no", "nah", "nope", "pass", "don't have")
                    ):
                        try:
                            rn = requests.post(
                                f"{NOTION_BASE}/search",
                                headers=self._headers(
                                    prefs["integration_token"]
                                ),
                                json={
                                    "query": notes_reply.strip()[:80],
                                    "page_size": 3,
                                    "filter": {
                                        "property": "object",
                                        "value": "page",
                                    },
                                },
                                timeout=10,
                            )
                            if (
                                rn.status_code == 200
                                and rn.json().get("results")
                            ):
                                prefs["notes_page_id"] = (
                                    rn.json()["results"][0]["id"]
                                )
                                await self._save_prefs(prefs)
                                await self.capability_worker.speak(
                                    "Done. Notes will go there now."
                                )
                            else:
                                await self.capability_worker.speak(
                                    "Couldn't find that page. "
                                    "Make sure it's shared with OpenHome."
                                )
                        except Exception:
                            await self.capability_worker.speak(
                                "Couldn't search right now. Try later."
                            )
                    continue

                await self._process_command(prefs, user_input)

        except Exception as e:
            self._log_err(f"Run loop error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()
