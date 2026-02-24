import json
import pathlib
import re
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"


#{{register_capability}}
class UpworkJobSearchCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        config_path = pathlib.Path(__file__).parent / "config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _clean_html(self, text: str) -> str:
        """Strip HTML tags and decode common HTML entities."""
        text = re.sub(
            r"<(br|p|div|li|tr|td|th|h[1-6])[^>]*>",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def _fetch_jobs_for_query(
        self, client: httpx.AsyncClient, query: str
    ) -> list:
        """Single HTTP call to Remotive; returns raw job list (may be empty)."""
        url = f"{REMOTIVE_API_URL}?{urlencode({'search': query, 'limit': 5})}"
        try:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
            )
            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[UpworkJobSearch] HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return []
            return response.json().get("jobs", [])
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[UpworkJobSearch] Request error: {e}"
            )
            return []

    async def search_jobs(self, query: str) -> Optional[List[dict]]:
        """Fetch the top 5 remote jobs matching the query from the Remotive API.

        Tries the full phrase first; if no results are returned, retries with
        just the most significant keyword (first word) as a fallback.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                raw_jobs = await self._fetch_jobs_for_query(client, query)

                if not raw_jobs:
                    first_keyword = (
                        query.strip().split()[0] if query.strip() else ""
                    )
                    if (
                        first_keyword
                        and first_keyword.lower() != query.strip().lower()
                    ):
                        raw_jobs = await self._fetch_jobs_for_query(
                            client, first_keyword
                        )

            if not raw_jobs:
                return None

            jobs = []
            for item in raw_jobs[:5]:
                description = self._clean_html(item.get("description", ""))
                if len(description) > 300:
                    description = description[:300] + "..."

                jobs.append(
                    {
                        "title": item.get("title", "Untitled"),
                        "company": item.get("company_name", "Unknown company"),
                        "description": description,
                        "link": item.get("url", ""),
                        "pub_date": item.get("publication_date", ""),
                        "salary": item.get("salary", "Not specified"),
                        "location": item.get(
                            "candidate_required_location", "Remote"
                        ),
                        "job_type": item.get("job_type", ""),
                    }
                )

            return jobs

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[UpworkJobSearch] Network error: {e}"
            )
            return None

    def format_job_for_speech(self, job: dict, index: int) -> str:
        title = job.get("title", "Untitled")
        company = job.get("company", "Unknown company")
        location = job.get("location", "Remote")
        salary = job.get("salary", "Not specified")
        description = job.get("description", "No description available.")
        short_desc = description[:150].rstrip()

        salary_part = (
            f" Salary: {salary}." if salary and salary != "Not specified" else ""
        )
        return (
            f"Job {index + 1}: {title} at {company}. "
            f"Location: {location}.{salary_part} "
            f"{short_desc}."
        )

    async def run(self):
        try:
            await self.capability_worker.speak(
                "I can help you find remote freelance jobs. "
                "What type of jobs are you looking for?"
            )

            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Please try again."
                )
                return

            await self.capability_worker.speak(
                f"Searching for {user_input} jobs..."
            )

            jobs = await self.search_jobs(user_input)

            if jobs:
                await self.capability_worker.speak(
                    f"I found {len(jobs)} jobs. Here are the top results."
                )
                for i, job in enumerate(jobs[:3]):
                    await self.capability_worker.speak(
                        self.format_job_for_speech(job, i)
                    )
            else:
                await self.capability_worker.speak(
                    "I couldn't find any jobs matching that search."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[UpworkJobSearch] Fatal error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong while searching."
            )

        finally:
            self.capability_worker.resume_normal_flow()
