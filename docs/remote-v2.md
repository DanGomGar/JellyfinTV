# `/remote`: TV11 EPG and current-program metadata

## Purpose

The remote interface provides a mobile-first EPG for the existing channels and a deliberately narrow control path for TV11. Version 2 keeps the original EPG and tuning behavior while adding the thumbnail and plot for the item currently airing on each channel.

The original v1 files are preserved locally as:

- `static/remote.html.bckp`
- `static/remote.css.bckp`
- `static/remote.js.bckp`

## Metadata source

Media files use a matching `.nfo` and `*-thumb.jpg`. Jellyfin already imports these resources:

- NFO `<plot>` becomes the Jellyfin `Overview` field.
- `*-thumb.jpg` becomes the Jellyfin `Thumb` image.

JellyfinTV consumes those imported resources through the authenticated Jellyfin API. The container does not mount `/srv/media`, and no media path or Jellyfin token is exposed to the browser.

## TV11 tuning

```text
POST /api/remote/tune/{channel_id}
```

The browser sends only the selected channel ID. The backend then:

1. Resolves the channel's current item and pseudo-live offset using the existing `/now` behavior.
2. Queries the current Jellyfin sessions.
3. Requires exactly one session matching TV11's stable `DeviceId`, client `Jellyfin for Tizen`, and device name `Samsung Smart TV`.
4. Verifies that the session reports media-control support.
5. Sends one Jellyfin `PlayNow` request for the current item with `StartPositionTicks = offset_seconds * 10,000,000`.

The ephemeral Jellyfin session ID is never stored. No stop, seek, queue, retry, generic device discovery, or multi-TV selection is performed. A successful HTTP response confirms only that Jellyfin accepted the command; physical playback on TV11 remains a separate functional check.

## API

### Current program

```text
GET /api/remote/channels/{channel_id}/current
```

This endpoint performs a read-only query against the existing `ScheduleItem` rows. It never calls refill and never changes the schedule. A successful response contains the current item identity, schedule boundaries, plot, and a local thumbnail URL.

If Jellyfin is not connected or metadata cannot be read, the endpoint still returns the current scheduled item with an empty plot and no thumbnail. This allows the EPG to remain usable with an explicit fallback.

### Thumbnail proxy

```text
GET /api/remote/items/{item_id}/thumb
```

The backend verifies that the item appears in the JellyfinTV schedule, requests Jellyfin's `Thumb` image at a maximum width of 640 pixels and quality 85, and returns the image with a one-hour browser cache policy.

The Jellyfin token remains in the backend headers and is never included in the HTML, JavaScript, image URL, or response body.

## Frontend behavior

- Every channel row displays its channel name, current thumbnail, current item title, and plot.
- Missing thumbnails and empty plots use visible fallbacks.
- Mixed thumbnail aspect ratios are preserved with `object-fit: contain` rather than cropped.
- Channels, schedules, and current metadata refresh once per minute.
- The AHORA line and current-program highlighting continue to move locally once per second.
- Tapping anywhere on a channel row continues to tune what `/now` reports at that moment; it does not play the visual block that was touched.
- No media is played on the phone.

## Operational notes

- Jellyfin must be connected after a JellyfinTV container restart because the current login token is memory-only.
- A metadata card can lag a schedule transition by at most one refresh interval (60 seconds).
- Five current library items have an empty NFO plot and will show `Sin descripción disponible.`
- Thumbnail URLs include Jellyfin's image tag as a cache-busting query parameter.
- The v2 metadata endpoints add no scheduler, library, channel, or media-file mutations.
- TV11 is intentionally the only supported playback target in this local implementation.
- Tuning fails closed if the TV11 session is absent, ambiguous, or does not support media control.
- Replacing the television or reinstalling its Jellyfin client may change its stable `DeviceId`; update the configured identity only after inspecting real Jellyfin sessions.

## Suggested commit scope

Suggested commit title:

```text
feat: add TV11 remote EPG with current metadata
```

Commit the active `static/remote.html`, `static/remote.css`, `static/remote.js`, remote endpoint changes in `main.py`, tests, and this document. The `.bckp` files are operational snapshots and should normally remain outside the main Git history because Git already provides versioning.
