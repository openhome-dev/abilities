import json
import os
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# UPWORK JOB SEARCH ABILITY
# Search for freelance jobs on Upwork using the Upwork GraphQL API
# Pattern: Speak → Ask for search query → Call API → Speak results → Exit
#
# Requires OAuth 2.0 authentication with Upwork API
# =============================================================================

# --- CONFIGURATION ---
# Get these from https://developers.upwork.com/
# Replace with your Upwork API credentials
UPWORK_CLIENT_KEY = "YOUR_UPWORK_CLIENT_KEY"
UPWORK_CLIENT_SECRET = "YOUR_UPWORK_CLIENT_SECRET"

# Upwork API endpoints
UPWORK_AUTH_URL = "https://www.upwork.com/api/v3/oauth2/token"
UPWORK_GRAPHQL_URL = "https://api.upwork.com/graphql/v2"


class UpworkJobSearchCapability(MatchingCapability):
    #{{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    access_token: str = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        from src.agent.capability_worker import CapabilityWorker
        capability_worker = CapabilityWorker(None)  # pass None if worker not available yet
        config_str = capability_worker.read_file("config.json")
        data = json.loads(config_str)

        #{{register capability}}
        return cls(
            unique_name=data['unique_name'],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def get_access_token(self) -> bool:
        """
        Get OAuth access token.
        In production, this would use proper OAuth flow.
        For this ability, users need to provide their own credentials.
        """
        try:
            # Create Basic auth header from client key and secret
            auth = (UPWORK_CLIENT_KEY, UPWORK_CLIENT_SECRET)

            # Request new token (in production, you'd cache this)
            response = requests.post(
                UPWORK_AUTH_URL,
                data={"grant_type": "client_credentials"},
                auth=auth,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                return True
            else:
                self.worker.editor_logging_handler.error(
                    f"[UpworkJobSearch] Auth failed: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[UpworkJobSearch] Auth error: {e}"
            )
            return False

    async def search_jobs(self, query: str, category: str = None) -> list | None:
        """
        Search for jobs using Upwork GraphQL API.
        Returns list of jobs or None on failure.
        """
        if not self.access_token:
            success = await self.get_access_token()
            if not success:
                return None

        # GraphQL query for job search
        graphql_query = {
            "query": """
            query JobSearch($query: String!, $first: Int!) {
                jobSearch(query: $query, first: $first) {
                    edges {
                        node {
                            title
                            description
                            skills
                            budget {
                                amount
                                currency
                            }
                            duration
                            workload
                            client {
                                feedback
                                reviewsCount
                                location {
                                    country
                                }
                            }
                            postedAt
                        }
                    }
                }
            }
            """,
            "variables": {
                "query": query,
                "first": 5  # Return top 5 results for voice response
            }
        }

        try:
            response = requests.post(
                UPWORK_GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                json=graphql_query,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()

                # Parse the GraphQL response
                jobs = []
                edges = data.get("data", {}).get("jobSearch", {}).get("edges", [])

                for edge in edges:
                    job = edge.get("node", {})
                    jobs.append({
                        "title": job.get("title", "Untitled"),
                        "description": job.get("description", "")[:200] + "..." if job.get("description") else "",
                        "skills": job.get("skills", []),
                        "budget": job.get("budget", {}),
                        "duration": job.get("duration", "Not specified"),
                        "workload": job.get("workload", "Not specified"),
                        "client_rating": job.get("client", {}).get("feedback", "N/A"),
                        "client_reviews": job.get("client", {}).get("reviewsCount", 0),
                        "client_country": job.get("client", {}).get("location", {}).get("country", "Unknown"),
                        "posted_at": job.get("postedAt", "")
                    })

                return jobs

            elif response.status_code == 401:
                # Token expired, try to refresh
                self.access_token = None
                return await self.search_jobs(query, category)
            else:
                self.worker.editor_logging_handler.error(
                    f"[UpworkJobSearch] API error: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[UpworkJobSearch] Search error: {e}")
            return None

    def format_job_for_speech(self, job: dict, index: int) -> str:
        """Format a job for voice response."""
        title = job.get("title", "Untitled")
        budget = job.get("budget", {})
        budget_str = f"{budget.get('amount', 'N/A')} {budget.get('currency', 'USD')}" if budget else "Budget not specified"
        duration = job.get("duration", "Not specified")
        workload = job.get("workload", "Not specified")
        rating = job.get("client_rating", "N/A")

        return f"Job {index + 1}: {title}. Budget: {budget_str}. Duration: {duration}. Workload: {workload}. Client rating: {rating} out of 5."

    async def run(self):
        """Main conversation flow."""
        try:
            # Step 1: Greet and explain
            await self.capability_worker.speak(
                "I can help you find freelance jobs on Upwork. What type of jobs are you looking for? "
                "For example, web development, mobile app, data entry, or copy writing."
            )

            # Step 2: Get search query from user
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Please try again with a job category or skill."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Step 3: Search for jobs
            await self.capability_worker.speak(
                f"Searching for {user_input} jobs on Upwork..."
            )

            jobs = await self.search_jobs(user_input)

            # Step 4: Speak results
            if jobs and len(jobs) > 0:
                await self.capability_worker.speak(
                    f"I found {len(jobs)} jobs matching '{user_input}'. Here are the top results:"
                )

                # Speak each job (limit to 3 for voice)
                for i, job in enumerate(jobs[:3]):
                    job_summary = self.format_job_for_speech(job, i)
                    await self.capability_worker.speak(job_summary)

                # Add closing message
                await self.capability_worker.speak(
                    "Would you like me to search for a different category? Say stop to exit."
                )

                # Listen for follow-up
                follow_up = await self.capability_worker.user_response()

                if follow_up and any(word in follow_up.lower() for word in ["yes", "sure", "another", "more", "search"]):
                    await self.capability_worker.speak("What would you like to search for?")
                    new_query = await self.capability_worker.user_response()
                    if new_query:
                        jobs = await self.search_jobs(new_query)
                        if jobs and len(jobs) > 0:
                            await self.capability_worker.speak(
                                f"I found {len(jobs)} jobs. Here are the results:"
                            )
                            for i, job in enumerate(jobs[:3]):
                                job_summary = self.format_job_for_speech(job, i)
                                await self.capability_worker.speak(job_summary)
                        else:
                            await self.capability_worker.speak(
                                "I couldn't find any jobs matching that search."
                            )
                else:
                    await self.capability_worker.speak(
                        "Happy job hunting! Talk to you later."
                    )
            else:
                await self.capability_worker.speak(
                    f"I couldn't find any jobs matching '{user_input}'. "
                    "Try a different category or skill. For example, Python programming, logo design, or content writing."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[UpworkJobSearch] Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong while searching for jobs. Please try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()
