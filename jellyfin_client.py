import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import PurePosixPath
from config import settings

def _validated_year(value: Any, fallback: int, current_year: int) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return fallback
    return year if 1900 <= year <= current_year else fallback

def source_name_from_path(path: Optional[str]) -> Optional[str]:
    """Return the immediate parent directory used as an item's source."""
    if not path:
        return None
    normalized = path.replace("\\", "/")
    if normalized.lower().endswith(".tmp.mp4"):
        return None
    parent = PurePosixPath(normalized).parent.name.strip()
    return parent or None

def filter_items_by_sources(
    items: List[Dict[str, Any]], sources: List[str]
) -> List[Dict[str, Any]]:
    """Keep items whose immediate parent directory is an allowed source."""
    allowed = set(sources)
    return [
        item
        for item in items
        if source_name_from_path(item.get("Path")) in allowed
    ]

class JellyfinClient:
    def __init__(self):
        self.base_url = settings.JELLYFIN_URL
        self.headers = {
            "X-Emby-Authorization": (
                'MediaBrowser Client="JellyfinTV", Device="Web", DeviceId="jellyfintv-server", Version="1.0.0"'
            )
        }
        if settings.JELLYFIN_TOKEN:
             self.headers["X-Emby-Token"] = settings.JELLYFIN_TOKEN

    def configure_connection(
        self,
        base_url: str,
        username: str,
        user_id: str,
        access_token: str,
    ) -> None:
        settings.JELLYFIN_URL = base_url.rstrip("/")
        settings.JELLYFIN_USERNAME = username
        settings.JELLYFIN_PASSWORD = ""
        settings.JELLYFIN_USER_ID = user_id
        settings.JELLYFIN_TOKEN = access_token
        self.base_url = settings.JELLYFIN_URL
        self.headers["X-Emby-Token"] = access_token

    def clear_connection(self) -> None:
        settings.JELLYFIN_URL = ""
        settings.JELLYFIN_USERNAME = ""
        settings.JELLYFIN_PASSWORD = ""
        settings.JELLYFIN_USER_ID = ""
        settings.JELLYFIN_TOKEN = ""
        self.base_url = ""
        self.headers.pop("X-Emby-Token", None)

    async def authenticate(
        self, base_url: str, username: str, password: str
    ) -> Optional[Dict[str, str]]:
        """Authenticate without mutating the active connection."""
        url = f"{base_url.rstrip('/')}/Users/AuthenticateByName"
        payload = {"Username": username, "Pw": password}
        headers = {
            "X-Emby-Authorization": self.headers["X-Emby-Authorization"]
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"Login failed: {exc}")
            return None

        token = data.get("AccessToken")
        user_id = data.get("User", {}).get("Id")
        if not token or not user_id:
            return None
        return {"access_token": token, "user_id": user_id}

    async def validate_connection(self) -> str:
        """Return valid, invalid, or unavailable for the configured token."""
        if not settings.JELLYFIN_TOKEN or not self.base_url:
            return "invalid"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/Users/Me", headers=self.headers
                )
        except httpx.HTTPError:
            return "unavailable"
        if response.status_code == 200:
            return "valid"
        if response.status_code in {401, 403}:
            return "invalid"
        return "unavailable"

    async def logout(self) -> None:
        if settings.JELLYFIN_TOKEN and self.base_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{self.base_url}/Sessions/Logout", headers=self.headers
                    )
            except httpx.HTTPError:
                pass
        self.clear_connection()

    async def login(self) -> bool:
        """Logs in and sets the token in settings/headers."""
        result = await self.authenticate(
            self.base_url,
            settings.JELLYFIN_USERNAME,
            settings.JELLYFIN_PASSWORD,
        )
        if not result:
            return False
        self.configure_connection(
            self.base_url,
            settings.JELLYFIN_USERNAME,
            result["user_id"],
            result["access_token"],
        )
        return True

    async def get_user_views(self) -> List[Dict[str, Any]]:
        """Gets top level user views (libraries)."""
        if not settings.JELLYFIN_TOKEN:
            return []
        
        url = f"{self.base_url}/Users/{self._get_user_id()}/Views"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json().get("Items", [])
        return []

    async def search_items(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search for items based on criteria.
        criteria can include: genres, years, tags, item_types (Movie,Episode)
        """
        if not settings.JELLYFIN_TOKEN:
            return []
        
        user_id = self._get_user_id()
        url = f"{self.base_url}/Users/{user_id}/Items"
        
        params = {
            "Recursive": "true",
            "Recursive": "true",
            "Fields": "Overview,Path,RunTimeTicks,ProductionYear,Genres,Tags,SeriesName,SeriesId,SeriesPrimaryImageTag,ImageTags",
            "IncludeItemTypes": ",".join(criteria.get("item_types", ["Movie", "Episode"])),
        }
        
        if criteria.get("genres"):
            params["Genres"] = "|".join(criteria.get("genres"))
            
        if criteria.get("years"):
            params["Years"] = ",".join(criteria.get("years"))
            
        if criteria.get("tags"):
            params["Tags"] = "|".join(criteria.get("tags"))
            
        if criteria.get("studios"):
            params["Studios"] = "|".join(criteria.get("studios"))
            
        if criteria.get("ratings"):
            params["OfficialRatings"] = "|".join(criteria.get("ratings"))

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return response.json().get("Items", [])
        return []

    async def get_sources(self) -> List[Dict[str, Any]]:
        """List immediate parent directories represented in the Jellyfin library."""
        items = await self.search_items({"item_types": ["Movie", "Episode"]})
        counts: Dict[str, int] = {}
        for item in items:
            source = source_name_from_path(item.get("Path"))
            if source:
                counts[source] = counts.get(source, 0) + 1
        return [
            {"id": source, "name": source, "item_count": count}
            for source, count in sorted(counts.items(), key=lambda pair: pair[0].casefold())
        ]

    def _get_user_id(self) -> str:
        if settings.JELLYFIN_USER_ID:
            return settings.JELLYFIN_USER_ID
        return "me"
        
    async def get_me(self) -> Optional[str]:
        url = f"{self.base_url}/Users/Me"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json().get("Id")
        return None

    async def get_genres(self) -> List[str]:
        """Fetches all genres from the library."""
        if not settings.JELLYFIN_TOKEN:
            return []
        
        user_id = self._get_user_id()
        url = f"{self.base_url}/Genres"
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "UserId": user_id
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return [item["Name"] for item in response.json().get("Items", [])]
        return []

    async def get_library_stats(self) -> Dict[str, Any]:
        """Fetches min/max years and other stats."""
        # Jellyfin doesn't have a direct "min/max year" endpoint easily.
        # We'll do a broad search for items to find years.
        # To be efficient, we might just hardcode reasonable defaults or fetch a subset.
        # Let's try to fetch all items (lightweight) to get years.
        current_year = datetime.now().year
        if not settings.JELLYFIN_TOKEN:
            return {"min_year": 1900, "max_year": current_year}
            
        user_id = self._get_user_id()
        url = f"{self.base_url}/Users/{user_id}/Items"
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "Fields": "ProductionYear",
            "SortBy": "ProductionYear",
            "SortOrder": "Ascending",
            "Limit": 1
        }
        
        min_year = 1900
        max_year = current_year
        
        async with httpx.AsyncClient() as client:
            # Get Min
            res_min = await client.get(url, headers=self.headers, params=params)
            if res_min.status_code == 200:
                items = res_min.json().get("Items", [])
                if items:
                    min_year = _validated_year(
                        items[0].get("ProductionYear"), 1900, current_year
                    )
            
            # Get Max
            params["SortOrder"] = "Descending"
            res_max = await client.get(url, headers=self.headers, params=params)
            if res_max.status_code == 200:
                items = res_max.json().get("Items", [])
                if items:
                    max_year = _validated_year(
                        items[0].get("ProductionYear"), current_year, current_year
                    )
                    
        return {"min_year": min_year, "max_year": max_year}

    async def get_tags(self) -> List[str]:
        """Fetches all tags from the library."""
        if not settings.JELLYFIN_TOKEN:
            return []
        
        # Tags endpoint usually exists or we search items for tags
        # /Tags endpoint exists in Jellyfin
        url = f"{self.base_url}/Tags"
        params = {"Recursive": "true"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return [item["Name"] for item in response.json().get("Items", [])]
        return []

    async def get_studios(self) -> List[str]:
        """Fetches all studios."""
        if not settings.JELLYFIN_TOKEN:
            return []
            
        url = f"{self.base_url}/Studios"
        params = {"Recursive": "true"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return [item["Name"] for item in response.json().get("Items", [])]
        return []

    async def get_ratings(self) -> List[str]:
        """Fetches content ratings (PG, R, etc)."""
        # No direct endpoint for "all used ratings", so we might need to search or use /Localization/ParentalRatings
        # But /Localization/ParentalRatings gives all *possible* ratings, not just used ones.
        # Let's use that for now as it's cleaner.
        if not settings.JELLYFIN_TOKEN:
            return []
            
        url = f"{self.base_url}/Localization/ParentalRatings"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 200:
                return [item["Name"] for item in response.json()]
        return []

jellyfin = JellyfinClient()
