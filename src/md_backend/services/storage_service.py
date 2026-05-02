"""Abstract storage service interface."""

from abc import ABC, abstractmethod


class StorageService(ABC):
    """Abstract base class for file storage backends."""

    @abstractmethod
    async def upload_file(
        self,
        file_bytes: bytes,
        storage_key: str,
        content_type: str,
    ) -> str:
        """Upload a file and return its public URL."""
        ...

