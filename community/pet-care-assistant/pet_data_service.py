"""Pet Data Service - Handles pet CRUD operations and file I/O.

Responsibilities:
- Load/save pet data from/to JSON files
- Resolve pet names (fuzzy matching)
- Pet CRUD operations
- Atomic file writes for data safety
"""

import json
from typing import Optional


class PetDataService:
    """Service for managing pet data and persistence."""

    def __init__(self, capability_worker, worker):
        """Initialize PetDataService.

        Args:
            capability_worker: CapabilityWorker for file I/O and user interaction
            worker: AgentWorker for logging
        """
        self.capability_worker = capability_worker
        self.worker = worker

    async def load_json(self, filename: str, default=None):
        """Load a JSON file, returning default if not found or corrupt.

        Args:
            filename: Name of file to load
            default: Default value if file doesn't exist or is corrupt

        Returns:
            Loaded JSON data or default value
        """
        if await self.capability_worker.check_if_file_exists(filename, False):
            try:
                raw = await self.capability_worker.read_file(filename, False)
                return json.loads(raw)
            except json.JSONDecodeError:
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Corrupt file {filename}, resetting."
                )
                await self.capability_worker.delete_file(filename, False)
        return default if default is not None else {}

    async def save_json(self, filename: str, data):
        """Save data using backup-write-delete pattern for data safety.

        Creates a backup before writing to prevent data loss. If write fails,
        backup remains for recovery. Not truly atomic, but much safer than
        delete-then-write.

        Pattern:
        1. Backup existing file (if exists)
        2. Write new data to target
        3. Delete backup on success
        4. If failure, backup retained for manual recovery

        Args:
            filename: Target filename to save to
            data: Data to serialize as JSON and save

        Raises:
            Exception: If write fails (backup file will remain)
        """
        backup_filename = f"{filename}.backup"

        try:
            # Create backup before overwriting
            if await self.capability_worker.check_if_file_exists(filename, False):
                content = await self.capability_worker.read_file(filename, False)
                await self.capability_worker.write_file(backup_filename, content, False)
                self.worker.editor_logging_handler.info(
                    f"[PetCare] Created backup: {backup_filename}"
                )

            await self.capability_worker.write_file(filename, json.dumps(data), False)

            if await self.capability_worker.check_if_file_exists(
                backup_filename, False
            ):
                await self.capability_worker.delete_file(backup_filename, False)
                self.worker.editor_logging_handler.info(
                    f"[PetCare] Successfully saved {filename}, backup cleaned up"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Failed to save {filename}: {e}"
            )
            # Backup file remains for manual recovery
            if await self.capability_worker.check_if_file_exists(
                backup_filename, False
            ):
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] Backup file {backup_filename} retained for recovery"
                )
            raise

    def resolve_pet(
        self, pet_data: dict, pet_name: Optional[str] = None
    ) -> Optional[dict]:
        """Resolve a pet name to a pet dict (synchronous).

        Args:
            pet_data: Pet data dict containing 'pets' list
            pet_name: Optional pet name to search for

        Returns:
            Matching pet dict or first pet if ambiguous, None if no pets
        """
        pets = pet_data.get("pets", [])

        if not pets:
            return None

        if len(pets) == 1:
            return pets[0]

        if pet_name:
            name_lower = pet_name.lower().strip()
            for p in pets:
                if p["name"].lower() == name_lower:
                    return p
            # Fuzzy: check if name starts with input or vice versa
            for p in pets:
                if p["name"].lower().startswith(name_lower) or name_lower.startswith(
                    p["name"].lower()
                ):
                    return p

        # Multiple pets, no match — return first pet as default
        # The caller should handle ambiguity at a higher level
        return pets[0]

    async def resolve_pet_async(
        self, pet_data: dict, pet_name: Optional[str] = None, is_exit_fn=None
    ) -> Optional[dict]:
        """Resolve a pet, asking the user if ambiguous (async).

        Args:
            pet_data: Pet data dict containing 'pets' list
            pet_name: Optional pet name to search for
            is_exit_fn: Optional function to check if user wants to exit

        Returns:
            Matching pet dict or None if user cancels
        """
        pets = pet_data.get("pets", [])
        if not pets:
            await self.capability_worker.speak("You don't have any pets set up yet.")
            return None

        if len(pets) == 1:
            return pets[0]

        if pet_name:
            name_lower = pet_name.lower().strip()
            for p in pets:
                if p["name"].lower() == name_lower:
                    return p
            # Fuzzy: check if name starts with input or vice versa
            for p in pets:
                if p["name"].lower().startswith(name_lower) or name_lower.startswith(
                    p["name"].lower()
                ):
                    return p

        names = " or ".join(p["name"] for p in pets)
        await self.capability_worker.speak(f"Which pet? {names}?")
        response = await self.capability_worker.user_response()

        if response and (not is_exit_fn or not is_exit_fn(response)):
            return self.resolve_pet(pet_data, response)
        return None
