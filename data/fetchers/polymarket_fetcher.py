import requests
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Macro-relevant market slugs to monitor
MACRO_MARKETS = {
    # CPI / Inflation
    "cpi_march": "march-inflation-us-annual",
    "inflation_peak_2026": "how-high-will-inflation-get-in-2026",
    # Fed
    "fed_april": "fed-decision-in-april",
    "fed_june": "fed-decision-in-june-825",
    "fed_cuts_2026": "how-many-fed-rate-cuts-in-2026",
    # Recession
    "recession_2026": "us-recession-by-end-of-2026",
    "negative_gdp": "negative-gdp-growth-in-2026",
}


class PolymarketFetcher:
    """获取 Polymarket 预测市场数据"""

    def __init__(self, custom_slugs: dict = None):
        self.slugs = custom_slugs or MACRO_MARKETS

    def fetch_all(self) -> dict:
        """Fetch all configured macro markets.

        Returns: {
            market_key: {
                "title": str,
                "slug": str,
                "outcomes": [
                    {"name": "Yes", "price": 0.355, "probability_pct": 35.5},
                    {"name": "No", "price": 0.645, "probability_pct": 64.5},
                ],
                "volume_24h": float,
                "liquidity": float,
                "fetched_at": str (ISO timestamp),
                "summary": str (one-line human-readable summary),
            },
            ...
        }
        """
        results = {}
        for key, slug in self.slugs.items():
            try:
                data = self._fetch_event(slug)
                if data:
                    results[key] = data
            except Exception as e:
                logger.warning(f"Failed to fetch Polymarket market {key} ({slug}): {e}")
        return results

    def _fetch_event(self, slug: str) -> dict | None:
        """Fetch a single event by slug."""
        resp = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=10)
        resp.raise_for_status()
        events = resp.json()

        if not events:
            return None

        event = events[0] if isinstance(events, list) else events

        title = event.get("title", slug)
        markets = event.get("markets", [])

        if not markets:
            return None

        # Parse all markets (outcomes) in this event
        outcomes = []
        total_volume = 0
        total_liquidity = 0

        for market in markets:
            outcome_name = market.get("groupItemTitle") or market.get("question", "")

            # outcomePrices is a JSON string like '["0.355","0.645"]'
            prices_raw = market.get("outcomePrices", "[]")
            try:
                if isinstance(prices_raw, str):
                    prices = json.loads(prices_raw)
                else:
                    prices = prices_raw
            except json.JSONDecodeError:
                prices = []

            # outcomes are typically ["Yes", "No"]
            outcome_labels = market.get("outcomes", "[]")
            if isinstance(outcome_labels, str):
                try:
                    outcome_labels = json.loads(outcome_labels)
                except json.JSONDecodeError:
                    outcome_labels = ["Yes", "No"]

            # For multi-market events (like "how many rate cuts"),
            # each market is one outcome with its Yes price
            if len(prices) >= 1:
                yes_price = float(prices[0])
                outcomes.append({
                    "name": outcome_name or (outcome_labels[0] if outcome_labels else "Yes"),
                    "price": yes_price,
                    "probability_pct": round(yes_price * 100, 1),
                })

            total_volume += float(market.get("volume24hr", 0) or 0)
            total_liquidity += float(market.get("liquidity", 0) or 0)

        # Sort by probability descending
        outcomes.sort(key=lambda x: x["probability_pct"], reverse=True)

        # Generate summary
        if outcomes:
            top = outcomes[0]
            summary = f"{title}: {top['name']} ({top['probability_pct']}%)"
        else:
            summary = title

        return {
            "title": title,
            "slug": slug,
            "outcomes": outcomes,
            "volume_24h": total_volume,
            "liquidity": total_liquidity,
            "fetched_at": datetime.now().isoformat(),
            "summary": summary,
        }

    def get_recession_probability(self) -> float | None:
        """Get the implied recession probability."""
        data = self.fetch_all()
        recession = data.get("recession_2026")
        if recession and recession["outcomes"]:
            for o in recession["outcomes"]:
                if "yes" in o["name"].lower():
                    return o["probability_pct"]
        return None

    def get_fed_decision(self, meeting: str = "april") -> dict | None:
        """Get the implied probabilities for a Fed meeting."""
        data = self.fetch_all()
        key = f"fed_{meeting}"
        return data.get(key)

    def get_cpi_consensus(self) -> dict | None:
        """Get market-implied CPI forecast."""
        data = self.fetch_all()
        return data.get("cpi_march")
