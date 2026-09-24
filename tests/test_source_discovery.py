import unittest

from jellyfin_client import filter_items_by_sources, source_name_from_path


class SourceDiscoveryTests(unittest.TestCase):
    def test_source_name_uses_immediate_parent(self):
        self.assertEqual(
            source_name_from_path("/srv/media/Familia/plex/scimandan/video.mp4"),
            "scimandan",
        )

    def test_source_name_supports_windows_separators(self):
        self.assertEqual(
            source_name_from_path(r"D:\media\click\video.mp4"),
            "click",
        )

    def test_temporary_video_is_not_eligible(self):
        self.assertIsNone(
            source_name_from_path("/srv/media/Familia/plex/click/video.tmp.mp4")
        )

    def test_source_filter_is_exact(self):
        items = [
            {"Id": "1", "Path": "/media/click/a.mp4"},
            {"Id": "2", "Path": "/media/click-extra/b.mp4"},
            {"Id": "3", "Path": "/media/scimandan/c.mp4"},
        ]
        self.assertEqual(
            [item["Id"] for item in filter_items_by_sources(items, ["click"])],
            ["1"],
        )

    def test_empty_source_list_matches_nothing(self):
        items = [{"Id": "1", "Path": "/media/click/a.mp4"}]
        self.assertEqual(filter_items_by_sources(items, []), [])


if __name__ == "__main__":
    unittest.main()
