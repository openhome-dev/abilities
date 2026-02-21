"""Activity Log Service - Handles activity tracking and logging.

Responsibilities:
- Add activities to log
- Query/filter activities
- Enforce log size limits
"""

from datetime import datetime
from typing import Optional


class ActivityLogService:
    """Service for managing activity logs."""

    def __init__(self, worker, max_log_entries=500):
        """Initialize ActivityLogService.

        Args:
            worker: AgentWorker for logging
            max_log_entries: Maximum number of log entries to keep
        """
        self.worker = worker
        self.max_log_entries = max_log_entries

    def add_activity(
        self,
        activity_log: list,
        pet_name: str,
        activity_type: str,
        details: str = "",
        value: float = None,
    ) -> list:
        """Add an activity to the log.

        Args:
            activity_log: Current activity log list
            pet_name: Name of the pet
            activity_type: Type of activity (feeding, walk, medication, etc.)
            details: Additional details about the activity
            value: Optional numeric value (e.g., weight in lbs)

        Returns:
            Updated activity log (with size limit enforced)
        """
        entry = {
            "pet_name": pet_name,
            "type": activity_type,
            "timestamp": datetime.now().isoformat(),
            "details": details,
        }
        if value is not None:
            entry["value"] = value

        activity_log.append(entry)

        if len(activity_log) > self.max_log_entries:
            removed = len(activity_log) - self.max_log_entries
            activity_log = activity_log[-self.max_log_entries:]
            self.worker.editor_logging_handler.warning(
                f"[PetCare] Activity log size limit reached. Removed {removed} old entries."
            )

        return activity_log

    def get_recent_activities(
        self,
        activity_log: list,
        pet_name: Optional[str] = None,
        activity_type: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        """Get recent activities, optionally filtered.

        Args:
            activity_log: Activity log list
            pet_name: Optional pet name filter
            activity_type: Optional activity type filter
            limit: Maximum number of activities to return

        Returns:
            List of matching activities (most recent first)
        """
        filtered = activity_log

        if pet_name:
            filtered = [a for a in filtered if a.get("pet_name") == pet_name]

        if activity_type:
            filtered = [a for a in filtered if a.get("type") == activity_type]

        # Return most recent first
        return list(reversed(filtered[-limit:]))
