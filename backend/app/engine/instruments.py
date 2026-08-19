"""The plottable-thing abstraction.

An RRG plots *something* against a benchmark. Whether that something is a sector index or an
individual stock changes nothing about the mathematics — the engine already takes two price
series and returns coordinates.

`Instrument` is the small adapter that lets one orchestration path serve both, instead of
duplicating `build_rrg` for stocks. It carries exactly the fields the payload builder needs
and nothing else, so neither the engine nor the service has to know which table a row came
from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

InstrumentLevel = Literal["sector", "stock"]


@dataclass(frozen=True)
class Instrument:
    """One plottable series: a sector index or an index constituent."""

    symbol: str
    #: Short label drawn on the chart next to the point.
    short_name: str
    #: Name used in tables and the detail panel.
    display_name: str
    #: Fully qualified name for tooltips.
    full_name: str
    color: str | None
    sort_order: int
    active: bool
    level: InstrumentLevel
    #: For stocks, the sector this membership belongs to. None for sectors themselves.
    parent_sector: str | None = None
    #: Date of the membership snapshot this row came from. None for sectors.
    as_of: str | None = None

    @classmethod
    def from_sector(cls, row) -> "Instrument":
        return cls(
            symbol=row.symbol,
            short_name=row.short_name,
            display_name=row.display_name,
            full_name=row.sector_name,
            color=row.color,
            sort_order=row.sort_order,
            active=row.active,
            level="sector",
        )

    @classmethod
    def from_stock(cls, row) -> "Instrument":
        return cls(
            symbol=row.symbol,
            # The NSE ticker is already the shortest unambiguous label, and it is what
            # traders read; abbreviating the company name further would only obscure it.
            short_name=row.symbol,
            display_name=row.symbol,
            full_name=row.company_name,
            color=row.color,
            sort_order=row.sort_order,
            active=row.active and row.data_available,
            level="stock",
            parent_sector=row.sector_symbol,
            as_of=row.as_of.isoformat() if row.as_of else None,
        )
