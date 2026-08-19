"""NSE provider -- intentionally a stub.

NSE has no public, documented historical-index API. The endpoints people use in
practice require a browser-like session (cookie handshake against the homepage first),
rate-limit aggressively, block datacentre IP ranges, and change shape without notice.
Shipping a scraper as the default data path would make the product's reliability depend
on an undocumented private endpoint.

So this class exists to hold the seam, not to pretend. Two honest routes to authoritative
NSE data:

1.  Licensed feed -- NSE Data Services or a redistributor. Implement `fetch` against
    their API; nothing else in the codebase changes.
2.  Bhavcopy / index CSV archives downloaded on a schedule into the CSV provider's
    directory. This keeps the licence position clean and needs no live scraping.

`fetch` raises rather than returning empty, so a misconfiguration surfaces immediately
instead of quietly producing an empty chart.
"""

from __future__ import annotations

from datetime import date

from .base import DataProvider, OHLCFrame, ProviderError


class NSEProvider(DataProvider):
    name = "nse"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch(
        self,
        provider_symbol: str,
        start: date | None = None,
        end: date | None = None,
    ) -> OHLCFrame:
        raise ProviderError(
            "The NSE provider is a deliberate stub. NSE publishes no supported "
            "historical-index API, and scraping the private endpoints is not a "
            "reliable production data path. Either point RRG_DATA_PROVIDER at 'csv' "
            "and land NSE index archives in the CSV directory, or implement this class "
            "against a licensed feed. See app/providers/nse.py for detail."
        )

    def health(self) -> dict:
        return {
            "provider": self.name,
            "status": "not_implemented",
            "detail": "stub; use csv with NSE archives, or a licensed feed",
        }
