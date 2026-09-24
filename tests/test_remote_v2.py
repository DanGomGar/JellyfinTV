import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

import main
from config import settings
from models import Channel, ScheduleItem


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "image/jpeg"}
    content = b"thumbnail"

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "Overview": "Plot imported from the NFO.",
            "ImageTags": {"Thumb": "thumb-tag"},
        }


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, *args, **kwargs):
        return FakeResponse()


class RemoteV2Tests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        channel = Channel(name="Test channel")
        self.session.add(channel)
        self.session.commit()
        self.session.refresh(channel)
        self.channel_id = channel.id
        now = datetime.now(timezone.utc)
        self.session.add(
            ScheduleItem(
                channel_id=self.channel_id,
                item_id="item-1",
                item_name="Current item",
                item_type="Movie",
                duration_seconds=3600,
                start_time=now - timedelta(minutes=10),
                end_time=now + timedelta(minutes=50),
            )
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_current_item_remains_available_without_jellyfin_login(self):
        with patch.object(settings, "JELLYFIN_TOKEN", ""):
            result = asyncio.run(
                main.get_remote_channel_current(self.channel_id, self.session)
            )

        self.assertEqual(result["status"], "playing")
        self.assertEqual(result["item_name"], "Current item")
        self.assertEqual(result["metadata_status"], "unavailable")
        self.assertIsNone(result["thumb_url"])

    def test_current_item_includes_plot_and_local_thumbnail_url(self):
        with patch.object(settings, "JELLYFIN_TOKEN", "token"), patch.object(
            main.httpx, "AsyncClient", FakeAsyncClient
        ):
            result = asyncio.run(
                main.get_remote_channel_current(self.channel_id, self.session)
            )

        self.assertEqual(result["metadata_status"], "available")
        self.assertEqual(result["plot"], "Plot imported from the NFO.")
        self.assertEqual(
            result["thumb_url"],
            "/api/remote/items/item-1/thumb?tag=thumb-tag",
        )

    def test_thumbnail_is_proxied_with_cache_policy(self):
        with patch.object(settings, "JELLYFIN_TOKEN", "token"), patch.object(
            main.httpx, "AsyncClient", FakeAsyncClient
        ):
            response = asyncio.run(
                main.get_remote_item_thumb("item-1", self.session)
            )

        self.assertEqual(response.body, b"thumbnail")
        self.assertEqual(response.headers["cache-control"], "public, max-age=3600")
        self.assertEqual(response.media_type, "image/jpeg")


if __name__ == "__main__":
    unittest.main()
