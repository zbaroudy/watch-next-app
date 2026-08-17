from pathlib import Path
import hashlib
import json
import re
import unicodedata

import requests


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key, logger):
        self.api_key = api_key
        self.logger = logger
        self.session = requests.Session()
        self.session.params = {
            "api_key": api_key,
            "language": "en-CA",
        }

    def _cache_key(self, media_type, title, year=None):
        value = f"{media_type}|{title}|{year or ''}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _normalize(self, value):
        value = unicodedata.normalize("NFKD", value)
        value = "".join(
            char for char in value
            if not unicodedata.combining(char)
        )
        value = value.lower()
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    def search(self, media_type, title, year=None):
        """
        Search TMDB for a title and cache the search response.
        media_type must be movie or tv.
        """
        if media_type not in ("movie", "tv"):
            raise ValueError("media_type must be 'movie' or 'tv'")

        cache_dir = Path("data/search") / media_type
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = (
            cache_dir
            / f"{self._cache_key(media_type, title, year)}.json"
        )

        if cache_file.exists():
            return json.loads(
                cache_file.read_text(encoding="utf-8")
            )

        endpoint = f"{self.BASE_URL}/search/{media_type}"

        params = {
            "query": title,
            "include_adult": "false",
            "page": 1,
        }

        if year:
            if media_type == "movie":
                params["year"] = year
            else:
                params["first_air_date_year"] = year

        self.logger.info(
            "TMDB search: %s | %s%s",
            media_type,
            title,
            f" | year={year}" if year else "",
        )

        response = self.session.get(
            endpoint,
            params=params,
            timeout=30,
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

        return data

    def resolve_title(self, title, media_type=None, flixpatrol_url=""):
        """
        Resolve a FlixPatrol title to a TMDB movie/TV ID.

        For movie/show charts, media_type is supplied by FlixPatrol.
        For Crave's mixed Overall chart, media_type is None and both
        TMDB endpoints are searched.
        """
        year = None
        match = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", flixpatrol_url or "")
        if match:
            year = int(match.group(0))

        types = [media_type] if media_type else ["movie", "tv"]
        target = self._normalize(title)

        candidates = []

        for candidate_type in types:
            data = self.search(candidate_type, title, year)
            for result in data.get("results", [])[:10]:
                result_title = (
                    result.get("title")
                    if candidate_type == "movie"
                    else result.get("name")
                ) or ""

                normalized = self._normalize(result_title)

                if normalized == target:
                    exact_bonus = 100
                elif target and (
                    target in normalized or normalized in target
                ):
                    exact_bonus = 55
                else:
                    exact_bonus = 0

                popularity = float(result.get("popularity") or 0)
                vote_count = float(result.get("vote_count") or 0)

                score = (
                    exact_bonus
                    + min(popularity, 100) * 0.10
                    + min(vote_count, 5000) / 5000 * 5
                )

                candidates.append({
                    "media_type": candidate_type,
                    "tmdb_id": result.get("id"),
                    "title": result_title,
                    "score": round(score, 3),
                    "popularity": popularity,
                    "vote_count": int(vote_count),
                    "release_date": (
                        result.get("release_date")
                        or result.get("first_air_date")
                        or ""
                    ),
                })

        candidates.sort(
            key=lambda item: (
                item["score"],
                item["popularity"],
                item["vote_count"],
            ),
            reverse=True,
        )

        if not candidates:
            return {
                "matched": False,
                "tmdb_id": None,
                "media_type": media_type,
                "confidence": "none",
                "candidates": [],
            }

        best = candidates[0]

        # Exact normalized title is the primary signal. If it isn't exact,
        # don't silently turn a fuzzy match into a confident match.
        exact = self._normalize(best["title"]) == target

        if exact and best["score"] >= 100:
            confidence = "high"
        elif best["score"] >= 55:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "matched": True,
            "tmdb_id": best["tmdb_id"],
            "media_type": best["media_type"],
            "confidence": confidence,
            "matched_title": best["title"],
            "candidates": candidates[:5],
        }

    def get_metadata(self, media_type, tmdb_id):
        """Return detailed TMDB metadata, using a local cache."""
        folder = "movie" if media_type == "movie" else "tv"

        cache_dir = Path("data/metadata") / folder
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / f"{tmdb_id}.json"

        if cache_file.exists():
            self.logger.info(
                "TMDB cache hit: %s %s",
                folder,
                tmdb_id,
            )
            return json.loads(
                cache_file.read_text(encoding="utf-8")
            )

        endpoint = (
            f"{self.BASE_URL}/movie/{tmdb_id}"
            if media_type == "movie"
            else f"{self.BASE_URL}/tv/{tmdb_id}"
        )

        if media_type == "movie":
            append = (
                "credits,videos,watch_providers,images,"
                "release_dates,recommendations,external_ids,"
                "keywords,similar"
            )
        else:
            append = (
                "credits,videos,watch_providers,images,"
                "content_ratings,recommendations,external_ids,"
                "keywords,similar"
            )

        self.logger.info(
            "Downloading TMDB metadata: %s %s",
            folder,
            tmdb_id,
        )

        response = self.session.get(
            endpoint,
            params={"append_to_response": append},
            timeout=30,
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

        return data
