from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from typing import List
import json
import httpx
from datetime import datetime, timezone

from database import create_db_and_tables, get_session
from models import Channel, ScheduleItem, ContentCriteria
from config import settings
from jellyfin_client import jellyfin
from scheduler import fill_channel_schedule

app = FastAPI()

TV11_DEVICE_ID = "TW96aWxsYS81LjAgKFNNQVJULVRWOyBMSU5VWDsgVGl6ZW4gNS4wKSBBcHBsZVdlYktpdC81MzcuMzYgKEtIVE1MLCBsaWtlIEdlY2tvKSBWZXJzaW9uLzUuMCBUViBTYWZhcmkvNTM3LjM2fDE3ODg0OTc5MzM5MTg1"
TV11_CLIENT = "Jellyfin for Tizen"
TV11_DEVICE_NAME = "Samsung Smart TV"

def validate_selection_criteria(criteria_json: str) -> None:
    try:
        criteria = json.loads(criteria_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid channel criteria") from exc

    selection_mode = criteria.get("selection_mode")
    if selection_mode is None:
        return
    if selection_mode not in {"all", "sources", "items"}:
        raise HTTPException(status_code=422, detail="Invalid content selection mode")
    if selection_mode == "sources":
        sources = criteria.get("sources")
        if not isinstance(sources, list) or not sources:
            raise HTTPException(status_code=422, detail="Select at least one source")
        if any(
            not isinstance(source, str)
            or not source.strip()
            or "/" in source
            or "\\" in source
            for source in sources
        ):
            raise HTTPException(status_code=422, detail="Invalid source identifier")
    if selection_mode == "items":
        item_ids = criteria.get("include_items")
        if not isinstance(item_ids, list) or not item_ids:
            raise HTTPException(status_code=422, detail="Select at least one item")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ads", StaticFiles(directory="ads"), name="ads")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# --- API Routes ---

@app.post("/api/login")
async def login(credentials: dict):
    settings.JELLYFIN_URL = credentials.get("url")
    settings.JELLYFIN_USERNAME = credentials.get("username")
    settings.JELLYFIN_PASSWORD = credentials.get("password")
    
    # Re-init client with new URL if needed (or just rely on settings)
    jellyfin.base_url = settings.JELLYFIN_URL
    
    success = await jellyfin.login()
    if not success:
        raise HTTPException(status_code=401, detail="Login failed")
    return {"status": "success"}

@app.get("/api/channels", response_model=List[Channel])
def get_channels(session: Session = Depends(get_session)):
    channels = session.exec(select(Channel)).all()
    return channels

@app.post("/api/channels", response_model=Channel)
def create_channel(channel: Channel, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    validate_selection_criteria(channel.criteria)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    background_tasks.add_task(fill_channel_schedule, channel.id)
    return channel

@app.put("/api/channels/{channel_id}", response_model=Channel)
def update_channel(channel_id: int, updated_channel: Channel, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    validate_selection_criteria(updated_channel.criteria)
        
    channel.name = updated_channel.name
    channel.criteria = updated_channel.criteria
    channel.ads_enabled = updated_channel.ads_enabled
    channel.ad_interval_mins = updated_channel.ad_interval_mins
    channel.ads_per_break = updated_channel.ads_per_break
    
    session.add(channel)
    session.commit()
    session.refresh(channel)
    
    # Trigger refill to apply new settings (might take time to propagate if schedule is full)
    # Ideally we'd clear future schedule but let's keep it simple
    background_tasks.add_task(fill_channel_schedule, channel.id)
    return channel

@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int, session: Session = Depends(get_session)):
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Delete associated schedule items first (cascade usually handles this but let's be safe or rely on SQLModel)
    # SQLModel relationships with cascade delete would be ideal, but manual delete is fine for now
    items = session.exec(select(ScheduleItem).where(ScheduleItem.channel_id == channel_id)).all()
    for item in items:
        session.delete(item)
        
    session.delete(channel)
    session.commit()
    return {"status": "deleted"}

@app.get("/api/channels/{channel_id}/now", response_model=dict)
async def get_channel_now(channel_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    # Find what's playing now
    now = datetime.now(timezone.utc)
    statement = select(ScheduleItem).where(
        ScheduleItem.channel_id == channel_id,
        ScheduleItem.start_time <= now,
        ScheduleItem.end_time > now
    )
    item = session.exec(statement).first()
    
    if not item:
        # Channel is offline/empty. Refill immediately!
        print(f"Channel {channel_id} is offline. Refilling now...")
        await fill_channel_schedule(channel_id)
        
        # Re-query
        item = session.exec(statement).first()
        
        if not item:
            # Still nothing? Maybe no content matches criteria.
            return {"status": "offline"}
            
    # Check if we need to top up the schedule (if less than 5 items remaining)
    future_count = session.exec(select(ScheduleItem).where(
        ScheduleItem.channel_id == channel_id,
        ScheduleItem.start_time > now
    )).all()
    
    if len(future_count) < 5:
        print(f"Channel {channel_id} running low. Scheduling refill.")
        background_tasks.add_task(fill_channel_schedule, channel_id)
        
    # Calculate offset
    offset_seconds = (now - item.start_time).total_seconds()
    
    # Adjust offset for mid-rolls
    final_offset = offset_seconds + item.media_start_offset
    
    return {
        "status": "playing",
        "item": item,
        "offset_seconds": final_offset,
        "is_ad": item.is_ad,
        "jellyfin_url": settings.JELLYFIN_URL,
        "jellyfin_token": settings.JELLYFIN_TOKEN
    }

@app.get("/api/channels/{channel_id}/schedule")
def get_channel_schedule(channel_id: int, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    statement = select(ScheduleItem).where(
        ScheduleItem.channel_id == channel_id,
        ScheduleItem.end_time > now
    ).order_by(ScheduleItem.start_time).limit(20)
    items = session.exec(statement).all()
    return items

@app.post("/api/channels/{channel_id}/refill")
async def refill_channel(channel_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(fill_channel_schedule, channel_id)
    return {"status": "scheduled"}

@app.post("/api/remote/tune/{channel_id}")
async def tune_tv11(
    channel_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    current = await get_channel_now(channel_id, background_tasks, session)
    if current.get("status") != "playing":
        raise HTTPException(status_code=409, detail="Channel is not currently playing")

    item = current["item"]
    offset_seconds = max(0.0, float(current["offset_seconds"]))
    start_position_ticks = int(offset_seconds * 10_000_000)

    if not settings.JELLYFIN_TOKEN:
        raise HTTPException(status_code=503, detail="Jellyfin is not connected")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sessions_response = await client.get(
                f"{jellyfin.base_url}/Sessions",
                headers=jellyfin.headers,
            )
            sessions_response.raise_for_status()
            matches = [
                candidate
                for candidate in sessions_response.json()
                if candidate.get("DeviceId") == TV11_DEVICE_ID
                and candidate.get("Client") == TV11_CLIENT
                and candidate.get("DeviceName") == TV11_DEVICE_NAME
            ]

            if len(matches) != 1:
                raise HTTPException(
                    status_code=503,
                    detail="TV11 session is unavailable or ambiguous",
                )

            tv11_session = matches[0]
            if not tv11_session.get("SupportsMediaControl"):
                raise HTTPException(
                    status_code=503,
                    detail="TV11 does not currently support media control",
                )

            play_response = await client.post(
                f"{jellyfin.base_url}/Sessions/{tv11_session['Id']}/Playing",
                headers=jellyfin.headers,
                params={
                    "playCommand": "PlayNow",
                    "itemIds": item.item_id,
                    "startPositionTicks": start_position_ticks,
                },
            )
            play_response.raise_for_status()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Jellyfin remote control request failed",
        ) from exc

    return {
        "status": "tuned",
        "channel_id": channel_id,
        "channel_name": channel.name,
        "item_id": item.item_id,
        "item_name": item.item_name,
        "offset_seconds": offset_seconds,
        "start_position_ticks": start_position_ticks,
        "device_name": TV11_DEVICE_NAME,
        "jellyfin_status_code": play_response.status_code,
    }

@app.get("/api/remote/channels/{channel_id}/current")
async def get_remote_channel_current(
    channel_id: int,
    session: Session = Depends(get_session),
):
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    now = datetime.now(timezone.utc)
    item = session.exec(
        select(ScheduleItem).where(
            ScheduleItem.channel_id == channel_id,
            ScheduleItem.start_time <= now,
            ScheduleItem.end_time > now,
        )
    ).first()
    if not item:
        return {"status": "offline", "channel_id": channel_id}

    result = {
        "status": "playing",
        "channel_id": channel_id,
        "item_id": item.item_id,
        "item_name": item.item_name,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "plot": "",
        "thumb_url": None,
        "metadata_status": "unavailable",
    }

    if item.is_ad:
        result["metadata_status"] = "not_applicable"
        return result
    if not settings.JELLYFIN_TOKEN:
        result["metadata_error"] = "Jellyfin is not connected"
        return result

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{jellyfin.base_url}/Items/{item.item_id}",
                headers=jellyfin.headers,
            )
            response.raise_for_status()
            metadata = response.json()
    except (httpx.HTTPError, ValueError):
        result["metadata_error"] = "Jellyfin metadata is unavailable"
        return result

    image_tag = metadata.get("ImageTags", {}).get("Thumb")
    result["plot"] = metadata.get("Overview") or ""
    result["metadata_status"] = "available"
    if image_tag:
        result["thumb_url"] = (
            f"/api/remote/items/{item.item_id}/thumb?tag={image_tag}"
        )
    return result

@app.get("/api/remote/items/{item_id}/thumb")
async def get_remote_item_thumb(
    item_id: str,
    session: Session = Depends(get_session),
):
    scheduled_item = session.exec(
        select(ScheduleItem).where(
            ScheduleItem.item_id == item_id,
            ScheduleItem.is_ad == False,
        )
    ).first()
    if not scheduled_item:
        raise HTTPException(status_code=404, detail="Scheduled item not found")
    if not settings.JELLYFIN_TOKEN:
        raise HTTPException(status_code=503, detail="Jellyfin is not connected")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{jellyfin.base_url}/Items/{item_id}/Images/Thumb",
                headers=jellyfin.headers,
                params={"maxWidth": 640, "quality": 85},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Jellyfin thumbnail is unavailable",
        ) from exc

    return Response(
        content=response.content,
        media_type=response.headers.get("Content-Type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=3600"},
    )

@app.get("/api/library/genres")
async def get_genres():
    return await jellyfin.get_genres()

@app.get("/api/library/stats")
async def get_stats():
    return await jellyfin.get_library_stats()

@app.get("/api/library/tags")
async def get_tags():
    return await jellyfin.get_tags()

@app.get("/api/library/studios")
async def get_studios():
    return await jellyfin.get_studios()

@app.get("/api/library/ratings")
async def get_ratings():
    return await jellyfin.get_ratings()

@app.get("/api/library/sources")
async def get_sources():
    return await jellyfin.get_sources()

@app.post("/api/library/search")
async def search_library(criteria: dict):
    # Wrapper to search items based on UI filters
    items = await jellyfin.search_items(criteria)
    
    # Deduplicate: Group by SeriesId
    unique_map = {}
    final_items = []
    
    content_types = criteria.get("content_types", [])
    # If empty, assume all
    if not content_types:
        content_types = ["Movie", "Series"]
        
    for item in items:
        # If it's an episode, use SeriesId as key. If Movie, use Id.
        series_id = item.get("SeriesId")
        item_id = item.get("Id")
        
        if series_id:
            # It's an episode (or part of a series)
            if "Series" not in content_types:
                continue
                
            if series_id not in unique_map:
                # Create a "Show" entry based on this episode
                # We want the Series Name and Series Image
                show_entry = {
                    "Id": series_id,
                    "Name": item.get("SeriesName", item.get("Name")), # Fallback if SeriesName missing
                    "ProductionYear": item.get("ProductionYear"),
                    "Type": "TV Series",
                    "ImageTag": item.get("SeriesPrimaryImageTag"), # Use Series image
                    "IsSeries": True,
                    "EpisodeCount": 1
                }
                unique_map[series_id] = show_entry
                final_items.append(show_entry)
            else:
                # Increment count
                unique_map[series_id]["EpisodeCount"] += 1
        else:
            # It's a Movie or something else without SeriesId
            if "Movie" not in content_types:
                continue
                
            if item_id not in unique_map:
                item["ImageTag"] = item.get("ImageTags", {}).get("Primary")
                item["IsSeries"] = False
                item["Type"] = "Movie" # Explicitly set for UI
                unique_map[item_id] = item
                final_items.append(item)
                
    return final_items

# Serve index
@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.get("/remote")
async def read_remote():
    return FileResponse('static/remote.html')

@app.get("/watch/{channel_id}")
async def watch_channel(channel_id: int):
    return FileResponse('static/channel.html')
