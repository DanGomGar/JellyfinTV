import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

import scheduler
from jellyfin_client import jellyfin
from models import Channel, ScheduleItem


class SourceSchedulerTests(unittest.TestCase):
    def test_source_mode_only_schedules_matching_directory(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            channel = Channel(
                name="Automatic source test",
                criteria=json.dumps(
                    {
                        "selection_mode": "sources",
                        "sources": ["click"],
                        "content_types": ["Movie"],
                    }
                ),
            )
            session.add(channel)
            session.commit()
            session.refresh(channel)
            channel_id = channel.id

        items = [
            {
                "Id": "click-item",
                "Name": "Click item",
                "Type": "Movie",
                "Path": "/media/click/a.mp4",
                "RunTimeTicks": 36_000_000_000,
                "ProductionYear": 2026,
            },
            {
                "Id": "crime-item",
                "Name": "Crime item",
                "Type": "Movie",
                "Path": "/media/fusgo/b.mp4",
                "RunTimeTicks": 36_000_000_000,
                "ProductionYear": 2026,
            },
        ]

        with patch.object(scheduler, "engine", engine), patch.object(
            jellyfin, "search_items", AsyncMock(return_value=items)
        ):
            asyncio.run(scheduler.fill_channel_schedule(channel_id, hours_to_fill=1))

        with Session(engine) as session:
            scheduled = session.exec(select(ScheduleItem)).all()

        self.assertTrue(scheduled)
        self.assertEqual({item.item_id for item in scheduled}, {"click-item"})


if __name__ == "__main__":
    unittest.main()
