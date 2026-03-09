from __future__ import annotations

import math
from typing import Any

import httpx

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import GeoPoint, LocalBusiness, LocalBusinessSearchResponse
from automation_intel_mcp.services.cache import FileCache


class GooglePlacesService:
    def __init__(self, settings: Settings, cache: FileCache) -> None:
        self.settings = settings
        self.cache = cache

    def _require_api_key(self) -> str:
        if not self.settings.google_maps_api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is missing. Add it to your .env file to use Google Places.")
        return self.settings.google_maps_api_key

    def _request_headers(self, api_key: str, field_mask: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
        }
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask
        return headers

    def _geocode_city(self, client: httpx.Client, city: str, api_key: str) -> GeoPoint:
        params = {
            "address": city,
            "key": api_key,
            "language": self.settings.google_places_language_code,
            "region": self.settings.google_places_region_code,
        }
        response = client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"Could not geocode city: {city}")

        location = ((results[0].get("geometry") or {}).get("location") or {})
        return GeoPoint(latitude=float(location["lat"]), longitude=float(location["lng"]))

    @staticmethod
    def _distance_meters(center: GeoPoint, latitude: float, longitude: float) -> int:
        earth_radius_m = 6371000
        lat1 = math.radians(center.latitude)
        lon1 = math.radians(center.longitude)
        lat2 = math.radians(latitude)
        lon2 = math.radians(longitude)

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return int(round(earth_radius_m * c))

    @staticmethod
    def _business_from_place(place: dict[str, Any], center: GeoPoint) -> LocalBusiness:
        location = place.get("location") or {}
        distance_meters: int | None = None
        if "latitude" in location and "longitude" in location:
            distance_meters = GooglePlacesService._distance_meters(
                center,
                latitude=float(location["latitude"]),
                longitude=float(location["longitude"]),
            )

        display_name = place.get("displayName") or {}
        return LocalBusiness(
            name=display_name.get("text") or "Unknown place",
            address=place.get("formattedAddress"),
            website=place.get("websiteUri"),
            phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
            rating=place.get("rating"),
            total_reviews=place.get("userRatingCount"),
            distance_meters=distance_meters,
        )

    def find_local_businesses(
        self,
        niche: str,
        city: str,
        radius_meters: int,
        *,
        max_results: int = 10,
    ) -> LocalBusinessSearchResponse:
        api_key = self._require_api_key()
        radius_meters = max(100, min(int(radius_meters), 50000))
        max_results = max(1, min(int(max_results), 20))

        cache_key = {
            "endpoint": "google_places_search_text",
            "niche": niche,
            "city": city,
            "radius_meters": radius_meters,
            "max_results": max_results,
            "language_code": self.settings.google_places_language_code,
            "region_code": self.settings.google_places_region_code,
        }
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached["cached"] = True
            return LocalBusinessSearchResponse.model_validate(cached)

        field_mask = ",".join(
            [
                "places.displayName",
                "places.formattedAddress",
                "places.websiteUri",
                "places.internationalPhoneNumber",
                "places.nationalPhoneNumber",
                "places.rating",
                "places.userRatingCount",
                "places.location",
            ]
        )

        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            center = self._geocode_city(client, city, api_key)
            payload = {
                "textQuery": f"{niche} em {city}",
                "languageCode": self.settings.google_places_language_code,
                "regionCode": self.settings.google_places_region_code,
                "pageSize": max_results,
                "locationBias": {
                    "circle": {
                        "center": {
                            "latitude": center.latitude,
                            "longitude": center.longitude,
                        },
                        "radius": float(radius_meters),
                    }
                },
            }
            response = client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=self._request_headers(api_key, field_mask),
                json=payload,
            )
            response.raise_for_status()
            places_payload = response.json()

        results: list[LocalBusiness] = []
        for place in places_payload.get("places") or []:
            business = self._business_from_place(place, center)
            if business.distance_meters is None or business.distance_meters <= radius_meters:
                results.append(business)

        results.sort(
            key=lambda item: (
                item.distance_meters if item.distance_meters is not None else 10**9,
                -(item.rating or 0.0),
                -(item.total_reviews or 0),
                item.name.lower(),
            )
        )
        result = LocalBusinessSearchResponse(
            niche=niche,
            city=city,
            radius_meters=radius_meters,
            center=center,
            results=results[:max_results],
            cached=False,
        )
        self.cache.set(cache_key, result.model_dump())
        return result
