"""Metadata interfaces for exchange trading rules."""

from __future__ import annotations

from typing import Protocol

from bot.storage.models import InstrumentConstraints


class InstrumentMetadataProvider(Protocol):
    """Protocol for instrument constraint lookup."""

    async def get_constraints(self, symbol: str) -> InstrumentConstraints:
        """Return exchange constraints for the given symbol."""
