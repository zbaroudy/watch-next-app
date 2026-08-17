from pathlib import Path
import json
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import trakt


app = FastAPI(title="FlixPatrol Canada Top 10")

BASE_DIR = Path("/app")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

OUTPUT_DIR = BASE_DIR / "data" / "output"

# Trakt/TMDB-resolved list data
TRAKT_DIR = BASE_DIR / "data" / "trakt"
TRAKT_ALL_LISTS_FILE = TRAKT_DIR / "tmdb_all_lists.json"

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/"
DISPLAY_TIMEZONE = "America/Toronto"
OMDB_API_KEY = os.getenv("OMDB_API_KEY", "").strip()
OMDB_CACHE_DIR = BASE_DIR / "data" / "omdb_cache"


PROVIDER_NAMES = {
    "netflix": "Netflix",
    "disney-plus": "Disney+",
    "prime-video": "Prime Video",
    "apple-tv-plus": "Apple TV+",
    "paramount-plus": "Paramount+",
    "crave": "Crave",
}

PROVIDER_NORMALIZATION = {
    "netflix": "Netflix",
    "disney": "Disney+",
    "disney+": "Disney+",
    "disney plus": "Disney+",

    "amazon prime video": "Prime Video",
    "prime video": "Prime Video",
    "prime video amazon channel": "Prime Video",
    "prime video with ads": "Prime Video",

    "apple tv": "Apple TV+",
    "apple tv+": "Apple TV+",
    "apple tv plus": "Apple TV+",

    "paramount": "Paramount+",
    "paramount+": "Paramount+",
    "paramount plus": "Paramount+",

    "crave": "Crave",

    "max": "Max",
    "hbo max": "Max",

    "peacock": "Peacock",

    "hulu": "Hulu",

    "mubi": "MUBI",

    "amc+": "AMC+",
    "amc plus": "AMC+",

    "starz": "STARZ",
    "starz entertainment": "STARZ",
}


def normalize_provider_name(provider_name):
    """
    Convert TMDB provider variants into a single canonical
    streaming service name.
    """

    name = (provider_name or "").strip()

    if not name:
        return None

    lower = name.lower()

    # -----------------------------------------------------
    # Exact/common variants
    # -----------------------------------------------------

    if lower in PROVIDER_NORMALIZATION:
        return PROVIDER_NORMALIZATION[lower]

    # -----------------------------------------------------
    # Paramount+
    # -----------------------------------------------------

    if "paramount" in lower:
        return "Paramount+"

    # -----------------------------------------------------
    # Netflix
    # -----------------------------------------------------

    if "netflix" in lower:
        return "Netflix"

    # -----------------------------------------------------
    # Disney+
    # -----------------------------------------------------

    if "disney" in lower:
        return "Disney+"

    # -----------------------------------------------------
    # Prime Video
    # -----------------------------------------------------

    if (
        "prime video" in lower
        or "amazon prime video" in lower
    ):
        return "Prime Video"

    # -----------------------------------------------------
    # Apple TV+
    # -----------------------------------------------------

    if (
        "apple tv" in lower
        or "apple tv+" in lower
        or "apple tv plus" in lower
    ):
        return "Apple TV+"

    # -----------------------------------------------------
    # Crave
    # -----------------------------------------------------

    if "crave" in lower:
        return "Crave"

    # -----------------------------------------------------
    # Max
    # -----------------------------------------------------

    if lower == "max" or "hbo max" in lower:
        return "Max"

    # -----------------------------------------------------
    # Peacock
    # -----------------------------------------------------

    if "peacock" in lower:
        return "Peacock"

    # -----------------------------------------------------
    # Hulu
    # -----------------------------------------------------

    if "hulu" in lower:
        return "Hulu"

    # -----------------------------------------------------
    # MUBI
    # -----------------------------------------------------

    if "mubi" in lower:
        return "MUBI"

    # -----------------------------------------------------
    # AMC+
    # -----------------------------------------------------

    if "amc+" in lower or "amc plus" in lower:
        return "AMC+"

    # -----------------------------------------------------
    # STARZ
    # -----------------------------------------------------

    if "starz" in lower:
        return "STARZ"

    # -----------------------------------------------------
    # Unknown provider
    #
    # Keep the original TMDB name rather than throwing it
    # away. This makes the system future-proof.
    # -----------------------------------------------------

    return name

def format_updated_timestamp(timestamp):
    if not timestamp:
        return ""

    try:
        dt = datetime.fromisoformat(timestamp)
        local_dt = dt.astimezone(ZoneInfo(DISPLAY_TIMEZONE))
        return local_dt.strftime("%b %-d, %Y at %-I:%M %p")
    except Exception:
        return timestamp


def format_date(value):
    if not value:
        return ""

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).strftime("%B %-d, %Y")
    except Exception:
        return value


def format_runtime(minutes):
    if not minutes:
        return ""

    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return ""

    hours, mins = divmod(minutes, 60)

    if hours and mins:
        return f"{hours}h {mins}m"

    if hours:
        return f"{hours}h"

    return f"{mins}m"


def get_directors(tmdb):
    credits = tmdb.get("credits") or {}
    crew = credits.get("crew") or []

    directors = []

    for person in crew:
        if person.get("job") != "Director":
            continue

        name = person.get("name")

        if name and name not in directors:
            directors.append(name)

    return directors[:5]


def get_creators(tmdb):
    creators = []

    for person in tmdb.get("created_by") or []:
        name = person.get("name")

        if name and name not in creators:
            creators.append(name)

    return creators[:5]


def get_cast(tmdb):
    credits = tmdb.get("credits") or {}
    cast = []

    for person in credits.get("cast") or []:
        name = person.get("name")

        if not name:
            continue

        profile_path = person.get("profile_path")

        cast.append({
            "name": name,
            "character": person.get("character") or "",
            "profile_url": (
                f"{TMDB_IMAGE_BASE}w185{profile_path}"
                if profile_path
                else None
            ),
        })

        if len(cast) >= 12:
            break

    return cast


def get_trailer(tmdb):
    videos = (
        (tmdb.get("videos") or {}).get("results")
        or []
    )

    candidates = [
        video
        for video in videos
        if video.get("site") == "YouTube"
        and video.get("type") == "Trailer"
    ]

    candidates.sort(
        key=lambda video: (
            bool(video.get("official")),
            video.get("published_at") or "",
        ),
        reverse=True,
    )

    if not candidates:
        candidates = [
            video
            for video in videos
            if video.get("site") == "YouTube"
            and video.get("type") in {
                "Teaser",
                "Clip",
            }
        ]

        candidates.sort(
            key=lambda video: (
                video.get("published_at") or ""
            ),
            reverse=True,
        )

    if not candidates:
        return None

    video = candidates[0]
    key = video.get("key")

    if not key:
        return None

    return {
        "key": key,
        "name": video.get("name") or "Trailer",
        "type": video.get("type") or "Trailer",
    }


def get_content_rating(tmdb, media_type):
    if media_type == "movie":
        results = (
            (tmdb.get("release_dates") or {}).get("results")
            or []
        )

        for country in results:
            if country.get("iso_3166_1") != "CA":
                continue

            for release in country.get("release_dates") or []:
                certification = (
                    release.get("certification") or ""
                ).strip()

                if certification:
                    return certification

        return ""

    results = (
        (tmdb.get("content_ratings") or {}).get("results")
        or []
    )

    for country in results:
        if country.get("iso_3166_1") != "CA":
            continue

        return (country.get("rating") or "").strip()

    # Canadian ratings are not always present in TMDB.
    # Fall back to US if there is no Canadian entry.
    for country in results:
        if country.get("iso_3166_1") == "US":
            return (country.get("rating") or "").strip()

    return ""


def get_omdb_ratings(imdb_id):
    if not OMDB_API_KEY or not imdb_id:
        return {}

    OMDB_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    cache_file = OMDB_CACHE_DIR / f"{imdb_id}.json"

    try:
        if cache_file.exists():
            data = json.loads(
                cache_file.read_text(
                    encoding="utf-8"
                )
            )
        else:
            response = requests.get(
                "https://www.omdbapi.com/",
                params={
                    "apikey": OMDB_API_KEY,
                    "i": imdb_id,
                    "plot": "short",
                },
                timeout=10,
            )

            response.raise_for_status()

            data = response.json()

            cache_file.write_text(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        if data.get("Response") != "True":
            return {}

        ratings = {}

        for rating in data.get("Ratings") or []:
            source = rating.get("Source")
            value = rating.get("Value")

            if source and value:
                ratings[source] = value

        if (
            data.get("imdbRating")
            and data.get("imdbRating") != "N/A"
        ):
            ratings["IMDb"] = data["imdbRating"]

        return ratings

    except Exception as exc:
        print(
            f"OMDb lookup failed for {imdb_id}: {exc}"
        )
        return {}

def get_tmdb_watch_providers(tmdb_id, media_type):
    """
    Get Canadian subscription streaming providers from TMDB
    and normalize/deduplicate provider variants.
    """

    try:
        endpoint = (
            "https://api.themoviedb.org/3/"
            f"{'movie' if media_type == 'movie' else 'tv'}"
            f"/{tmdb_id}/watch/providers"
        )

        response = requests.get(
            endpoint,
            params={
                "api_key": os.getenv(
                    "TMDB_API_KEY",
                    "",
                ),
            },
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        canada = (
            (data.get("results") or {})
            .get("CA")
            or {}
        )

        providers = []
        seen_providers = set()

        for provider in canada.get("flatrate") or []:

            provider_name = (
                provider.get("provider_name") or ""
            ).strip()

            logo_path = provider.get("logo_path")

            if not provider_name:
                continue

            # Normalize TMDB's provider name
            normalized_name = normalize_provider_name(
                provider_name
            )

            if not normalized_name:
                continue

            # Deduplicate after normalization
            dedupe_key = normalized_name.lower()

            if dedupe_key in seen_providers:
                continue

            seen_providers.add(dedupe_key)

            providers.append({
                "id": provider.get("provider_id"),
                "name": normalized_name,
                "logo_url": (
                    f"{TMDB_IMAGE_BASE}w92{logo_path}"
                    if logo_path
                    else None
                ),
            })

        return providers

    except Exception as exc:
        print(
            f"TMDB watch provider lookup failed "
            f"for {media_type}/{tmdb_id}: {exc}"
        )

        return []

def prepare_detail_item(item):
    tmdb = item.get("tmdb") or {}

    media_type = (
        item.get("_resolved_media_type")
        or item.get("media_type")
    )

    # -----------------------------------------------------
    # Common display fields
    #
    # FlixPatrol items normally get these from load_lists().
    # Trakt fallback items need them populated here.
    # -----------------------------------------------------

    item["_resolved_media_type"] = media_type

    if media_type == "movie":
        item["_title"] = (
            tmdb.get("title")
            or tmdb.get("original_title")
            or item.get("title")
            or "Unknown"
        )

        release_date = (
            tmdb.get("release_date")
            or ""
        )

    else:
        item["_title"] = (
            tmdb.get("name")
            or tmdb.get("original_name")
            or item.get("title")
            or "Unknown"
        )

        release_date = (
            tmdb.get("first_air_date")
            or ""
        )

    item["_year"] = (
        release_date[:4]
        if release_date
        else ""
    )

    poster_path = tmdb.get("poster_path")

    item["_poster_url"] = (
        f"{TMDB_IMAGE_BASE}w500{poster_path}"
        if poster_path
        else None
    )

    backdrop_path = tmdb.get("backdrop_path")

    item["_backdrop_url"] = (
        f"{TMDB_IMAGE_BASE}w1280{backdrop_path}"
        if backdrop_path
        else None
    )

    item["_overview"] = (
        tmdb.get("overview")
        or ""
    )

    item["_rating"] = tmdb.get(
        "vote_average"
    )

    item["_genres"] = [
        genre.get("name")
        for genre in tmdb.get("genres", [])
        if genre.get("name")
    ]

    release_date = (
        tmdb.get("release_date")
        if media_type == "movie"
        else tmdb.get("first_air_date")
    ) or ""

    last_air_date = (
        tmdb.get("last_air_date")
        or ""
    )

    item["_release_date"] = format_date(
        release_date
    )

    item["_last_air_date"] = format_date(
        last_air_date
    )

    item["_runtime"] = format_runtime(
        tmdb.get("runtime")
        if media_type == "movie"
        else (
            tmdb.get("episode_run_time")
            or [None]
        )[0]
    )

    item["_status"] = tmdb.get("status") or ""

    item["_content_rating"] = get_content_rating(
        tmdb,
        media_type,
    )

    item["_directors"] = get_directors(tmdb)
    item["_creators"] = get_creators(tmdb)
    item["_cast"] = get_cast(tmdb)
    item["_trailer"] = get_trailer(tmdb)

    item["_imdb_id"] = (
        (tmdb.get("external_ids") or {}).get(
            "imdb_id"
        )
    )

    item["_omdb_ratings"] = get_omdb_ratings(
        item["_imdb_id"]
    )

    item["_rating_count"] = (
        tmdb.get("vote_count") or 0
    )

    item["_vote_average"] = tmdb.get(
        "vote_average"
    )

    item["_seasons"] = tmdb.get(
        "number_of_seasons"
    )

    item["_episodes"] = tmdb.get(
        "number_of_episodes"
    )

    # Canadian streaming providers from TMDB
    item["_watch_providers"] = get_tmdb_watch_providers(
        item.get("tmdb_id"),
        media_type,
    )

    # -----------------------------------------------------
    # Streaming service
    #
    # For Trakt titles, determine the actual Canadian
    # streaming service from TMDB.
    # -----------------------------------------------------

    item["_watch_providers"] = get_tmdb_watch_providers(
        item.get("tmdb_id"),
        media_type,
    )

    if item["_watch_providers"]:
        item["_service_provider"] = ", ".join(
            provider["name"]
            for provider in item["_watch_providers"]
            if provider.get("name")
        )
    else:
        item["_service_provider"] = None


# =========================================================
# TRAKT DATA
# =========================================================

def load_trakt_title(tmdb_id, media_type):
    """
    Find a TMDB-resolved Trakt title by TMDB ID and media type.

    This is used only as a fallback when a title is not present
    in the normal FlixPatrol lists.
    """

    if not TRAKT_ALL_LISTS_FILE.exists():
        return None

    try:
        data = json.loads(
            TRAKT_ALL_LISTS_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        print(
            f"Failed to load Trakt data: {exc}"
        )
        return None

    wanted_type = (
        "movie"
        if media_type == "movie"
        else "show"
    )

    # The resolver output is normally a list.
    # Be tolerant if it is wrapped in a dictionary.
    if isinstance(data, dict):
        entries = data.get("items") or data.get(
            "matches"
        ) or []

        if not entries:
            entries = []

            for value in data.values():
                if isinstance(value, list):
                    entries.extend(value)
    else:
        entries = data

    for entry in entries:

        if not isinstance(entry, dict):
            continue

        if str(entry.get("tmdb_id")) != str(tmdb_id):
            continue

        entry_type = (
            entry.get("tmdb_type")
            or entry.get("type")
        )

        if entry_type != wanted_type:
            continue

        tmdb_date = (
            entry.get("tmdb_date")
            or ""
        )

        tmdb = {
            "id": entry.get("tmdb_id"),

            "title": (
                entry.get("tmdb_title")
                if wanted_type == "movie"
                else None
            ),

            "name": (
                entry.get("tmdb_title")
                if wanted_type == "show"
                else None
            ),

            "original_title": (
                entry.get("tmdb_original_title")
                if wanted_type == "movie"
                else None
            ),

            "original_name": (
                entry.get("tmdb_original_title")
                if wanted_type == "show"
                else None
            ),

            "release_date": (
                tmdb_date
                if wanted_type == "movie"
                else ""
            ),

            "first_air_date": (
                tmdb_date
                if wanted_type == "show"
                else ""
            ),

            "overview": (
                entry.get("tmdb_overview")
                or ""
            ),

            "poster_path": entry.get(
                "tmdb_poster_path"
            ),

            "backdrop_path": entry.get(
                "tmdb_backdrop_path"
            ),

            "vote_average": entry.get(
                "tmdb_vote_average"
            ),

            "vote_count": entry.get(
                "tmdb_vote_count"
            ),
        }

        item = {
            "rank": None,

            "title": entry.get("title") or "",

            "media_type": wanted_type,

            "tmdb_id": entry.get("tmdb_id"),

            "tmdb": tmdb,

            "trakt_id": entry.get("trakt_id"),

            "trakt_image_url": entry.get(
                "trakt_image_url"
            ),

            "list_name": entry.get(
                "list_name"
            ),

            "list_slug": entry.get(
                "list_slug"
            ),

            "match_method": entry.get(
                "match_method"
            ),

            "match_confidence": entry.get(
                "match_confidence"
            ),
        }

        list_data = {
            "provider": "trakt",

            "provider_display": "Trakt",

            "country": "CA",

            "media_type": wanted_type,

            "name": entry.get(
                "list_name"
            ),

            "list_name": entry.get(
                "list_name"
            ),

            "slug": entry.get(
                "list_slug"
            ),

            "list_slug": entry.get(
                "list_slug"
            ),

            "updated": None,

            "updated_display": "",
        }

        return {
            "item": item,
            "list": list_data,
        }

    return None


# =========================================================
# TRAKT JSON API
# =========================================================

@app.get("/api/trakt/stats")
async def api_trakt_stats():
    return trakt.get_stats()


@app.get("/api/trakt/lists")
async def api_trakt_lists():
    lists = trakt.get_lists()

    return {
        "lists": lists,
        "total_lists": len(lists),
    }


@app.get("/api/trakt/lists/{slug}")
async def api_trakt_list(slug: str):
    return trakt.get_list(slug)


# =========================================================
# FLIXPATROL LIST LOADING
# =========================================================

def load_lists():
    lists = []

    if not OUTPUT_DIR.exists():
        return lists

    FLIXPATROL_FILES = [
        "netflix-movie-ca.json",
        "netflix-tv-ca.json",
        "disney-plus-movie-ca.json",
        "disney-plus-tv-ca.json",
        "prime-video-movie-ca.json",
        "prime-video-tv-ca.json",
        "apple-tv-plus-movie-ca.json",
        "apple-tv-plus-tv-ca.json",
        "paramount-plus-movie-ca.json",
        "paramount-plus-tv-ca.json",
        "crave-overall-ca.json",
    ]

    for filename in FLIXPATROL_FILES:

        path = OUTPUT_DIR / filename

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            data.setdefault(
                "provider",
                "unknown",
            )

            provider_key = str(
                data["provider"]
            ).strip().lower()

            data["provider_display"] = (
                data.get("provider_display")
                or PROVIDER_NAMES.get(
                    provider_key,
                    provider_key.title(),
                )
            )

            data.setdefault(
                "country",
                "CA",
            )

            data.setdefault(
                "media_type",
                "unknown",
            )

            data.setdefault(
                "items",
                [],
            )

            data["updated_display"] = (
                format_updated_timestamp(
                    data.get("updated")
                )
            )

            for item in data["items"]:

                tmdb = item.get("tmdb") or {}

                title = (
                    tmdb.get("title")
                    or tmdb.get("name")
                    or item.get("title")
                    or "Unknown"
                )

                release_date = (
                    tmdb.get("release_date")
                    or tmdb.get("first_air_date")
                    or ""
                )

                item["_title"] = title

                item["_year"] = (
                    release_date[:4]
                    if release_date
                    else ""
                )

                poster_path = tmdb.get(
                    "poster_path"
                )

                item["_poster_url"] = (
                    f"{TMDB_IMAGE_BASE}w500{poster_path}"
                    if poster_path
                    else None
                )

                backdrop_path = tmdb.get(
                    "backdrop_path"
                )

                item["_backdrop_url"] = (
                    f"{TMDB_IMAGE_BASE}w1280{backdrop_path}"
                    if backdrop_path
                    else None
                )

                item["_overview"] = (
                    tmdb.get("overview", "")
                )

                item["_rating"] = tmdb.get(
                    "vote_average"
                )

                item["_genres"] = [
                    genre.get("name")
                    for genre in tmdb.get(
                        "genres",
                        [],
                    )
                    if genre.get("name")
                ]

                # Crave Overall is a mixed list.
                if data["media_type"] == "overall":

                    item["_resolved_media_type"] = (
                        item.get("media_type")
                        or (
                            item.get(
                                "tmdb_match"
                            )
                            or {}
                        ).get(
                            "media_type"
                        )
                    )

                else:

                    item["_resolved_media_type"] = (
                        "movie"
                        if data["media_type"]
                        == "movie"
                        else "tv"
                    )

            lists.append(data)

        except Exception as exc:
            print(
                f"Failed to load {path}: {exc}"
            )

    return lists


# =========================================================
# WEB UI
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def home(request: Request):

    lists = load_lists()

    providers = []

    for list_data in lists:

        provider = list_data.get(
            "provider",
            "unknown",
        )

        display = list_data.get(
            "provider_display",
            provider,
        )

        if not any(
            p["value"] == provider
            for p in providers
        ):

            providers.append({
                "value": provider,
                "display": display,
            })

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "lists": lists,
            "providers": providers,
        },
    )


@app.get(
    "/categories",
    response_class=HTMLResponse,
)
async def categories(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="categories.html",
        context={},
    )


# =========================================================
# HTML TITLE DETAILS
# =========================================================

@app.get(
    "/title/{media_type}/{tmdb_id}",
    response_class=HTMLResponse,
)
async def title_details(
    request: Request,
    media_type: str,
    tmdb_id: int,
):
    from_page = request.query_params.get("from", "home")

    media_type = media_type.strip().lower()

    lists = load_lists()
    title_data = None

    # -----------------------------------------------------
    # 1. Existing FlixPatrol lookup
    # -----------------------------------------------------

    for list_data in lists:

        for item in list_data.get(
            "items",
            [],
        ):

            if str(
                item.get("tmdb_id")
            ) != str(tmdb_id):
                continue

            resolved = (
                item.get(
                    "_resolved_media_type"
                )
            )

            if resolved != media_type:
                continue

            title_data = {
                "item": item,
                "list": list_data,
            }

            break

        if title_data:
            break

    # -----------------------------------------------------
    # 2. Trakt fallback
    # -----------------------------------------------------

    if not title_data:

        title_data = load_trakt_title(
            tmdb_id,
            media_type,
        )


    # -----------------------------------------------------
    # 3. Direct TMDB fallback
    #
    # If the title came from a Trakt list but isn't present
    # in the local resolver file, use the TMDB ID directly.
    # -----------------------------------------------------

    if not title_data:

        title_data = {
            "item": {
                "rank": None,
                "title": "",
                "media_type": media_type,
                "tmdb_id": tmdb_id,
                "tmdb": {},
                "trakt_id": None,
                "trakt_image_url": None,
            },

            "list": {
                "provider": "trakt",
                "provider_display": "Trakt",
                "country": "CA",
                "media_type": media_type,
                "name": "Trakt List",
                "list_name": "Trakt List",
                "slug": "",
                "list_slug": "",
                "updated": None,
                "updated_display": "",
            },
        }

    item = title_data["item"]

    # -----------------------------------------------------
    # 3. Fetch complete TMDB metadata
    #
    # Trakt resolver gives us the TMDB ID and basic
    # metadata. The full TMDB request provides credits,
    # videos, ratings, content ratings, etc.
    # -----------------------------------------------------

    try:

        tmdb_id_value = item.get(
            "tmdb_id"
        )

        if tmdb_id_value:

            tmdb_endpoint = (
                "https://api.themoviedb.org/3/"
                f"{'movie' if media_type == 'movie' else 'tv'}"
                f"/{tmdb_id_value}"
            )

            append = (
                "credits,"
                "videos,"
                "release_dates,"
                "content_ratings,"
                "external_ids"
            )

            response = requests.get(
                tmdb_endpoint,
                params={
                    "api_key": os.getenv(
                        "TMDB_API_KEY",
                        "",
                    ),
                    "language": "en-CA",
                    "append_to_response": append,
                },
                timeout=30,
            )

            response.raise_for_status()

            full_tmdb = response.json()

            item["tmdb"] = full_tmdb

    except Exception as exc:

        print(
            f"TMDB detail enrichment failed for "
            f"{media_type}/{tmdb_id}: {exc}"
        )

    prepare_detail_item(item)

    if from_page == "categories":
        back_url = "/categories"
        back_text = "← Back to Categories"
    else:
        back_url = "/"
        back_text = "← Back to Top 10"

    return templates.TemplateResponse(
        request=request,
        name="details.html",
        context={
            "item": item,
            "list": title_data["list"],
            "back_url": back_url,
            "back_text": back_text,
        },
    )


# =========================================================
# JSON API
# =========================================================

def api_item(item, list_data):
    """
    Convert an internal list item into the public JSON
    representation used by the Apple TV app and other clients.
    """

    tmdb = item.get("tmdb") or {}

    media_type = (
        item.get("_resolved_media_type")
        or item.get("media_type")
        or list_data.get("media_type")
    )

    title = (
        item.get("_title")
        or tmdb.get("title")
        or tmdb.get("name")
        or item.get("title")
        or "Unknown"
    )

    release_date = (
        tmdb.get("release_date")
        if media_type == "movie"
        else tmdb.get("first_air_date")
    ) or ""

    return {
        "rank": item.get("rank"),

        "tmdb_id": item.get("tmdb_id"),

        "media_type": media_type,

        "title": title,

        "year": (
            release_date[:4]
            if release_date
            else ""
        ),

        "release_date": release_date,

        "poster_url": item.get(
            "_poster_url"
        ),

        "backdrop_url": item.get(
            "_backdrop_url"
        ),

        "overview": (
            item.get("_overview")
            or ""
        ),

        "tmdb_rating": item.get(
            "_vote_average"
        ),

        "tmdb_votes": (
            item.get("_rating_count")
            or 0
        ),

        "provider": list_data.get(
            "provider"
        ),

        "provider_display": list_data.get(
            "provider_display"
        ),

        "country": list_data.get(
            "country",
            "CA",
        ),
    }


@app.get("/api/lists")
async def api_lists():
    """
    Return all available Canadian streaming lists.
    """

    lists = load_lists()

    result = []

    for list_data in lists:

        items = [
            api_item(
                item,
                list_data,
            )
            for item in list_data.get(
                "items",
                [],
            )
        ]

        result.append({
            "provider": list_data.get(
                "provider"
            ),

            "provider_display": list_data.get(
                "provider_display"
            ),

            "country": list_data.get(
                "country",
                "CA",
            ),

            "media_type": list_data.get(
                "media_type"
            ),

            "updated": list_data.get(
                "updated"
            ),

            "updated_display": list_data.get(
                "updated_display"
            ),

            "items": items,
        })

    return {
        "country": "CA",
        "lists": result,
    }


@app.get(
    "/api/lists/{provider}/{media_type}"
)
async def api_list(
    provider: str,
    media_type: str,
):

    provider = provider.strip().lower()
    media_type = media_type.strip().lower()

    lists = load_lists()

    for list_data in lists:

        list_provider = str(
            list_data.get(
                "provider",
                "",
            )
        ).strip().lower()

        list_media_type = str(
            list_data.get(
                "media_type",
                "",
            )
        ).strip().lower()

        if list_provider != provider:
            continue

        # Crave uses an overall mixed list.
        if list_media_type == "overall":

            filtered_items = [
                item
                for item in list_data.get(
                    "items",
                    [],
                )
                if (
                    item.get(
                        "_resolved_media_type"
                    )
                    or item.get(
                        "media_type"
                    )
                ) == media_type
            ]

        elif list_media_type == media_type:

            filtered_items = (
                list_data.get(
                    "items",
                    [],
                )
            )

        else:
            continue

        return {
            "provider": list_data.get(
                "provider"
            ),

            "provider_display": list_data.get(
                "provider_display"
            ),

            "country": list_data.get(
                "country",
                "CA",
            ),

            "media_type": media_type,

            "updated": list_data.get(
                "updated"
            ),

            "updated_display": list_data.get(
                "updated_display"
            ),

            "items": [
                api_item(
                    item,
                    list_data,
                )
                for item in filtered_items
            ],
        }

    return {
        "error": "List not found",
        "provider": provider,
        "media_type": media_type,
    }


@app.get(
    "/api/title/{media_type}/{tmdb_id}"
)
async def api_title(
    media_type: str,
    tmdb_id: int,
):

    media_type = media_type.strip().lower()

    lists = load_lists()

    # -----------------------------------------------------
    # 1. Existing FlixPatrol lookup
    # -----------------------------------------------------

    for list_data in lists:

        for item in list_data.get(
            "items",
            [],
        ):

            if str(
                item.get("tmdb_id")
            ) != str(tmdb_id):
                continue

            resolved_type = (
                item.get(
                    "_resolved_media_type"
                )
                or item.get(
                    "media_type"
                )
            )

            if resolved_type != media_type:
                continue

            prepare_detail_item(item)

            tmdb = item.get(
                "tmdb"
            ) or {}

            result = api_item(
                item,
                list_data,
            )

            result.update({

                "status": (
                    item.get(
                        "_status"
                    )
                    or ""
                ),

                "content_rating": (
                    item.get(
                        "_content_rating"
                    )
                    or ""
                ),

                "runtime": (
                    item.get(
                        "_runtime"
                    )
                    or ""
                ),

                "seasons": item.get(
                    "_seasons"
                ),

                "episodes": item.get(
                    "_episodes"
                ),

                "last_air_date": (
                    item.get(
                        "_last_air_date"
                    )
                    or ""
                ),

                "genres": (
                    item.get(
                        "_genres"
                    )
                    or []
                ),

                "directors": (
                    item.get(
                        "_directors"
                    )
                    or []
                ),

                "creators": (
                    item.get(
                        "_creators"
                    )
                    or []
                ),

                "cast": (
                    item.get(
                        "_cast"
                    )
                    or []
                ),

                "imdb_id": item.get(
                    "_imdb_id"
                ),

                "ratings": (
                    item.get(
                        "_omdb_ratings"
                    )
                    or {}
                ),

                "trailer": item.get(
                    "_trailer"
                ),

                "watch_providers": (
                    item.get(
                        "_watch_providers"
                    )
                    or []
                ),

                "tmdb_url": (
                    "https://www.themoviedb.org/"
                    f"{media_type}/{tmdb_id}"
                ),

                "seerr_url": (
                    "https://requests.ziadbaroudy.com/"
                    f"{media_type}/{tmdb_id}"
                ),

            })

            return result

    # -----------------------------------------------------
    # 2. Trakt fallback
    # -----------------------------------------------------

    trakt_title = load_trakt_title(
        tmdb_id,
        media_type,
    )

    if trakt_title:

        item = trakt_title["item"]
        list_data = trakt_title["list"]

        # -------------------------------------------------
        # Fetch complete TMDB metadata
        # -------------------------------------------------

        try:

            tmdb_endpoint = (
                "https://api.themoviedb.org/3/"
                f"{'movie' if media_type == 'movie' else 'tv'}"
                f"/{tmdb_id}"
            )

            append = (
                "credits,"
                "videos,"
                "release_dates,"
                "content_ratings,"
                "external_ids"
            )

            response = requests.get(
                tmdb_endpoint,
                params={
                    "api_key": os.getenv(
                        "TMDB_API_KEY",
                        "",
                    ),
                    "language": "en-CA",
                    "append_to_response": append,
                },
                timeout=30,
            )

            response.raise_for_status()

            item["tmdb"] = response.json()

        except Exception as exc:

            print(
                f"TMDB API detail enrichment failed "
                f"for Trakt title {tmdb_id}: {exc}"
            )

        prepare_detail_item(item)

        result = api_item(
            item,
            list_data,
        )

        result.update({

            "status": (
                item.get("_status")
                or ""
            ),

            "content_rating": (
                item.get(
                    "_content_rating"
                )
                or ""
            ),

            "runtime": (
                item.get(
                    "_runtime"
                )
                or ""
            ),

            "seasons": item.get(
                "_seasons"
            ),

            "episodes": item.get(
                "_episodes"
            ),

            "last_air_date": (
                item.get(
                    "_last_air_date"
                )
                or ""
            ),

            "genres": (
                item.get(
                    "_genres"
                )
                or []
            ),

            "directors": (
                item.get(
                    "_directors"
                )
                or []
            ),

            "creators": (
                item.get(
                    "_creators"
                )
                or []
            ),

            "cast": (
                item.get(
                    "_cast"
                )
                or []
            ),

            "imdb_id": item.get(
                "_imdb_id"
            ),

            "ratings": (
                item.get(
                    "_omdb_ratings"
                )
                or {}
            ),

            "trailer": item.get(
                "_trailer"
            ),

            "tmdb_url": (
                "https://www.themoviedb.org/"
                f"{media_type}/{tmdb_id}"
            ),

            "seerr_url": (
                "https://requests.ziadbaroudy.com/"
                f"{media_type}/{tmdb_id}"
            ),

            # Explicitly identify this as a Trakt fallback.
            "source": "trakt",

            "trakt_id": item.get(
                "trakt_id"
            ),

            "trakt_list_name": item.get(
                "list_name"
            ),

            "trakt_list_slug": item.get(
                "list_slug"
            ),

            "trakt_match_method": item.get(
                "match_method"
            ),

            "trakt_match_confidence": item.get(
                "match_confidence"
            ),

        })

        return result

    return {
        "error": "Title not found",
        "media_type": media_type,
        "tmdb_id": tmdb_id,
    }
