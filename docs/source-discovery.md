# Automatic source discovery

## Purpose

Automatic source discovery lets a channel use all current Jellyfin items from one or more source directories without storing a permanent list of Jellyfin item IDs. New content becomes eligible the next time JellyfinTV normally extends that channel's schedule.

Discovery does not scan the filesystem and does not ask Jellyfin to refresh a library. Jellyfin must index a file before JellyfinTV can discover it.

## Source identity

JellyfinTV requests the `Path` field for library items and treats the immediate parent directory as the source name.

Example:

```text
/srv/media/Familia/plex/scimandan/video.mp4
                                └─ source: scimandan
```

Temporary files ending in `.tmp.mp4` are ignored. Source names are matched exactly and are case-sensitive.

This model is intended for libraries where playable files live directly inside one directory per source. Nested season directories require a future, explicitly defined source-root strategy.

## Selection modes

### All matching content

```json
{
  "selection_mode": "all",
  "content_types": ["Movie"]
}
```

Every Jellyfin item matching the remaining filters is eligible. This is the behavior used by an unrestricted random channel.

### Automatic sources

```json
{
  "selection_mode": "sources",
  "sources": ["scimandan", "click"],
  "content_types": ["Movie"]
}
```

The source list is persistent configuration. Jellyfin item IDs are resolved again immediately before schedule generation.

### Manual items

```json
{
  "selection_mode": "items",
  "include_items": ["jellyfin-item-id-1", "jellyfin-item-id-2"],
  "content_types": ["Movie"]
}
```

This preserves the existing fixed-item behavior. Legacy criteria containing `include_items` without `selection_mode` continue to work as manual selections.

## Scheduling sequence

The normal refill entry points continue to call `fill_channel_schedule`.

For a source-based channel, the function now performs:

1. Read the channel criteria.
2. Query the current Jellyfin items using the existing filters.
3. Keep items whose immediate parent directory matches a configured source.
4. Pass that candidate list to the existing random schedule generator.

Existing `ScheduleItem` rows are not deleted, replaced, or reordered. The discovery step only affects entries created during that invocation. The 24-hour fill horizon, random selection, duration handling, advertisements, and top-up triggers are unchanged.

Newly discovered content becomes eligible; random selection does not guarantee that it will appear immediately.

## API

`GET /api/library/sources` returns the source directories currently represented in Jellyfin:

```json
[
  {"id": "click", "name": "click", "item_count": 27},
  {"id": "scimandan", "name": "scimandan", "item_count": 39}
]
```

Absolute media paths and Jellyfin credentials are not returned to the browser.

## Failure behavior

- A source-based channel with no configured sources is not filled.
- If Jellyfin is unavailable or returns no candidates, no schedule entries are added.
- An empty or failed discovery is never interpreted as permission to use the entire library.
- Existing schedule entries remain intact if discovery fails.
- Removing a file prevents it from being selected for future entries after Jellyfin removes it from the library. An already scheduled reference is not purged by this feature.

## Gideon-Server channel migration

The current thematic channels should use these source definitions:

| Channel | Sources |
| --- | --- |
| Ciencia y Tecnología | `scimandan`, `click`, `facuperalta`, `sorprendente` |
| Crimen y Casos | `fusgo`, `fusgotv`, `c4jiménezoficial` |
| Chespirito y Comedia | `redhood33`, `loscaquitos90`, `chavo`, `ocurrencia` |
| Negocios y Consumo | `8va`, `unpesodesalsas` |
| Aleatorio | `selection_mode: all` |

The existing schedule must remain in place during migration. Only the criteria JSON changes.

## Validation checklist

1. `GET /api/library/sources` returns every expected source with its current item count.
2. Creating and editing each selection mode preserves its corresponding criteria.
3. A source-based channel excludes items from unselected directories.
4. Adding an indexed Jellyfin item increases its source count and makes the item eligible on the next normal refill.
5. Existing schedule rows are unchanged by discovery or criteria migration.
6. Manual and unrestricted channels retain their previous behavior.
7. `.tmp.mp4` paths are not exposed as sources or candidates.
8. A failed or empty discovery does not broaden a channel to the full library.

## Commit scope

Suggested commit title:

```text
feat: add automatic channel source discovery
```

The source-discovery commit consists of:

- `jellyfin_client.py`: request item paths, derive source names, list sources, and filter candidates.
- `scheduler.py`: apply source discovery immediately before the existing generator.
- `main.py`: expose the source-list endpoint and validate explicit selection modes.
- `static/index.html`: add all-content, automatic-source, and manual-item modes to channel creation and editing.
- `tests/`: cover path parsing, exact source filtering, temporary-file exclusion, and scheduler isolation.
- `README.md` and this document: describe the feature and its operational semantics.

The SQLite criteria migration is installation data and is not part of the Git commit. Database files and their backups must remain untracked.
