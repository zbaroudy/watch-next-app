import json
import os
import re
import time

import requests
from dotenv import load_dotenv


INPUT_FILE = "/app/output/all_lists.json"
OUTPUT_FILE = "/app/data/trakt/tmdb_all_lists.json"
FAILED_FILE = "/app/data/trakt/tmdb_all_lists_failed.json"

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_SESSION = requests.Session()


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_API_KEY")

if not TMDB_API_KEY:
    raise RuntimeError(
        "TMDB_API_KEY was not found in .env"
    )


# --------------------------------------------------
# Title normalization
# --------------------------------------------------

def normalize_title(title):
    """
    Normalize a title to make fuzzy-ish comparisons
    easier.
    """

    if not title:
        return ""

    title = title.lower()

    # Remove zero-width Unicode characters
    title = re.sub(
        r"[\u200b-\u200f\u2060\ufeff]",
        "",
        title
    )

    # Replace punctuation with spaces
    title = re.sub(
        r"[^a-z0-9\s]",
        " ",
        title
    )

    # Collapse multiple spaces
    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


# --------------------------------------------------
# TMDB API request
# --------------------------------------------------

def tmdb_request(endpoint, params):
    """
    Perform a TMDB API request.
    """

    params = {
        **params,
        "api_key": TMDB_API_KEY,
        "language": "en-US",
    }

    response = TMDB_SESSION.get(
        f"{TMDB_BASE_URL}{endpoint}",
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# --------------------------------------------------
# TMDB searches
# --------------------------------------------------

def search_tmdb_exact_title_year(item):
    """
    Level 1:
    Exact title + year.
    """

    title = item["title"]
    media_type = item["type"]
    year = item.get("year")

    if media_type == "movie":

        params = {
            "query": title,
            "include_adult": "false",
        }

        if year:
            params["year"] = year

        data = tmdb_request(
            "/search/movie",
            params
        )

    elif media_type == "show":

        params = {
            "query": title,
            "include_adult": "false",
        }

        if year:
            params["first_air_date_year"] = year

        data = tmdb_request(
            "/search/tv",
            params
        )

    else:
        return []

    return data.get(
        "results",
        []
    )


def search_tmdb_title_only(item):
    """
    Level 2:
    Exact title, no year restriction.
    """

    title = item["title"]
    media_type = item["type"]

    if media_type == "movie":

        data = tmdb_request(
            "/search/movie",
            {
                "query": title,
                "include_adult": "false",
            }
        )

    elif media_type == "show":

        data = tmdb_request(
            "/search/tv",
            {
                "query": title,
                "include_adult": "false",
            }
        )

    else:
        return []

    return data.get(
        "results",
        []
    )


# --------------------------------------------------
# Result comparison
# --------------------------------------------------

def get_result_title(result, media_type):
    """
    Get the appropriate title field from TMDB.
    """

    if media_type == "movie":

        return (
            result.get("title")
            or result.get("original_title")
            or ""
        )

    return (
        result.get("name")
        or result.get("original_name")
        or ""
    )


def get_result_original_title(
    result,
    media_type
):
    """
    Get the original title/name from TMDB.
    """

    if media_type == "movie":

        return (
            result.get("original_title")
            or ""
        )

    return (
        result.get("original_name")
        or ""
    )


def get_result_year(
    result,
    media_type
):
    """
    Extract the release/first-air year.
    """

    if media_type == "movie":

        date = result.get(
            "release_date"
        )

    else:

        date = result.get(
            "first_air_date"
        )

    if not date:
        return None

    try:

        return int(date[:4])

    except (
        ValueError,
        TypeError
    ):

        return None


# --------------------------------------------------
# Token comparison
# --------------------------------------------------

def get_title_tokens(title):

    normalized = normalize_title(
        title
    )

    if not normalized:
        return set()

    return set(
        normalized.split()
    )


def get_title_overlap(
    trakt_title,
    tmdb_title
):
    """
    Return the percentage of Trakt title
    words appearing in the TMDB title.
    """

    trakt_words = get_title_tokens(
        trakt_title
    )

    tmdb_words = get_title_tokens(
        tmdb_title
    )

    if not trakt_words or not tmdb_words:
        return 0

    return (
        len(
            trakt_words
            & tmdb_words
        )
        / len(trakt_words)
    )


# --------------------------------------------------
# Result scoring
# --------------------------------------------------

def score_result(item, result):
    """
    Score a TMDB result against the original
    Trakt item.

    Higher = better match.
    """

    title = item["title"]
    year = item.get("year")
    media_type = item["type"]

    trakt_title = normalize_title(
        title
    )

    tmdb_title = normalize_title(
        get_result_title(
            result,
            media_type
        )
    )

    tmdb_original_title = normalize_title(
        get_result_original_title(
            result,
            media_type
        )
    )

    tmdb_year = get_result_year(
        result,
        media_type
    )

    score = 0

    # ----------------------------------------------
    # Title comparison
    # ----------------------------------------------

    if (
        tmdb_title == trakt_title
        or tmdb_original_title == trakt_title
    ):

        score += 70

    elif (
        trakt_title in tmdb_title
        or tmdb_title in trakt_title
        or trakt_title in tmdb_original_title
        or tmdb_original_title in trakt_title
    ):

        score += 45

    else:

        # Check both displayed and original title
        overlap_display = get_title_overlap(
            title,
            get_result_title(
                result,
                media_type
            )
        )

        overlap_original = get_title_overlap(
            title,
            get_result_original_title(
                result,
                media_type
            )
        )

        overlap = max(
            overlap_display,
            overlap_original
        )

        if overlap > 0:

            score += int(
                overlap * 40
            )

    # ----------------------------------------------
    # Year comparison
    # ----------------------------------------------

    if (
        year
        and tmdb_year
    ):

        if tmdb_year == year:

            score += 30

        elif abs(
            tmdb_year - year
        ) <= 1:

            score += 10

    return score


# --------------------------------------------------
# Choose best result
# --------------------------------------------------

def choose_best_result(
    item,
    results,
    minimum_score=70
):
    """
    Choose the highest scoring TMDB result.

    Returns:
        (result, score)
    """

    if not results:
        return None, 0

    scored = []

    for result in results:

        score = score_result(
            item,
            result
        )

        scored.append(
            (
                score,
                result
            )
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    best_score, best_result = (
        scored[0]
    )

    if best_score < minimum_score:

        return None, best_score

    return (
        best_result,
        best_score
    )


# --------------------------------------------------
# Match methods
# --------------------------------------------------

def resolve_item(item):
    """
    Attempt to resolve a Trakt item through
    progressively broader searches.

    Levels:

    1. Exact title + year
    2. Exact title, no year
    3. Normalized title + year
    4. Normalized title, no year
    5. Title variant + matching year
    6. Exact title + year mismatch
    """

    title = item["title"]
    year = item.get("year")
    media_type = item["type"]

    # ----------------------------------------------
    # LEVEL 1
    # Exact title + year
    # ----------------------------------------------

    print(
        "  Trying Level 1: "
        "title + year..."
    )

    results = search_tmdb_exact_title_year(
        item
    )

    best, score = choose_best_result(
        item,
        results,
        minimum_score=90
    )

    if best:

        return {
            "result": best,
            "score": score,
            "method": "title_year_exact",
            "confidence": "high",
        }

    # ----------------------------------------------
    # LEVEL 2
    # Exact title only
    # ----------------------------------------------

    print(
        "  Trying Level 2: "
        "title only..."
    )

    results = search_tmdb_title_only(
        item
    )

    best, score = choose_best_result(
        item,
        results,
        minimum_score=70
    )

    if best:

        tmdb_year = get_result_year(
            best,
            media_type
        )

        # If we have a known year and the
        # TMDB result has a wildly different
        # year, don't automatically accept it.
        if (
            year
            and tmdb_year
            and abs(
                tmdb_year - year
            ) > 3
        ):

            best = None

        if best:

            # Exact title + no Trakt year
            # is a high-confidence match.
            if (
                not year
                and score >= 70
            ):

                confidence = "high"

            else:

                confidence = (
                    "high"
                    if score >= 90
                    else "medium"
                )

            return {
                "result": best,
                "score": score,
                "method": "title_exact",
                "confidence": confidence,
            }

    # ----------------------------------------------
    # LEVEL 3
    # Normalized title + year
    # ----------------------------------------------

    print(
        "  Trying Level 3: "
        "normalized title + year..."
    )

    normalized = normalize_title(
        title
    )

    normalized_item = {
        **item,
        "title": normalized,
    }

    results = search_tmdb_exact_title_year(
        normalized_item
    )

    best, score = choose_best_result(
        item,
        results,
        minimum_score=75
    )

    if best:

        return {
            "result": best,
            "score": score,
            "method": "title_normalized_year",
            "confidence": "medium",
        }

    # ----------------------------------------------
    # LEVEL 4
    # Normalized title only
    # ----------------------------------------------

    print(
        "  Trying Level 4: "
        "normalized title..."
    )

    results = search_tmdb_title_only(
        normalized_item
    )

    best, score = choose_best_result(
        item,
        results,
        minimum_score=75
    )

    if best:

        tmdb_year = get_result_year(
            best,
            media_type
        )

        # Don't accept a clearly unrelated
        # result just because the title is similar.
        if (
            year
            and tmdb_year
            and abs(
                tmdb_year - year
            ) > 5
        ):

            best = None

        if best:

            return {
                "result": best,
                "score": score,
                "method": "title_normalized",
                "confidence": "medium",
            }

    # ----------------------------------------------
    # LEVEL 5
    # Title variant + matching year
    #
    # This handles things such as:
    #
    # Trakt:
    #   American Detective with Lt. Joe Kenda
    #
    # TMDB:
    #   Homicide Hunter: American Detective
    #
    # The title isn't identical, but TMDB's search
    # has returned a candidate with the same year
    # and meaningful title overlap.
    # ----------------------------------------------

    print(
        "  Trying Level 5: "
        "title variant + matching year..."
    )

    if year:

        # We already searched title + year above.
        # Reuse those results rather than making
        # another API request.
        variant_candidates = results

        # At this point "results" is from Level 4.
        # Therefore perform the proper title+year
        # search again for Level 5.
        variant_candidates = (
            search_tmdb_exact_title_year(
                item
            )
        )

        variant_scored = []

        for candidate in variant_candidates:

            candidate_year = get_result_year(
                candidate,
                media_type
            )

            if candidate_year != year:
                continue

            display_title = (
                get_result_title(
                    candidate,
                    media_type
                )
            )

            original_title = (
                get_result_original_title(
                    candidate,
                    media_type
                )
            )

            display_overlap = (
                get_title_overlap(
                    title,
                    display_title
                )
            )

            original_overlap = (
                get_title_overlap(
                    title,
                    original_title
                )
            )

            overlap = max(
                display_overlap,
                original_overlap
            )

            candidate_score = score_result(
                item,
                candidate
            )

            # We need at least some meaningful
            # title overlap.
            #
            # 25% is enough for cases such as:
            #
            # "American Detective with Lt. Joe Kenda"
            #
            # vs.
            #
            # "Homicide Hunter: American Detective"
            #
            if overlap >= 0.25:

                variant_scored.append(
                    (
                        candidate_score,
                        overlap,
                        candidate
                    )
                )

        if variant_scored:

            variant_scored.sort(
                key=lambda x: (
                    x[0],
                    x[1]
                ),
                reverse=True
            )

            variant_score, overlap, best = (
                variant_scored[0]
            )

            return {
                "result": best,
                "score": variant_score,
                "method": "title_variant_year",
                "confidence": "medium",
            }

    # ----------------------------------------------
    # LEVEL 6
    # Exact title + year mismatch
    #
    # This is deliberately AFTER all of the
    # original matching logic.
    #
    # Example:
    #
    # Trakt:
    #   Unusual Suspects (2001)
    #
    # TMDB:
    #   Unusual Suspects (2010)
    #
    # We only accept this fallback when:
    #
    #   1. The TMDB title is an exact normalized
    #      title match.
    #
    #   2. There is exactly ONE exact-title
    #      candidate.
    #
    #   3. TMDB has a valid year.
    #
    # This prevents us from blindly choosing
    # between multiple identically titled shows.
    # ----------------------------------------------

    print(
        "  Trying Level 6: "
        "exact title + year mismatch..."
    )

    # We need the title-only results.
    # 'results' currently contains Level 5's
    # title+year search, so perform the title-only
    # search here.
    mismatch_candidates = (
        search_tmdb_title_only(
            item
        )
    )

    exact_candidates = []

    normalized_trakt_title = normalize_title(
        title
    )

    for candidate in mismatch_candidates:

        candidate_title = get_result_title(
            candidate,
            media_type
        )

        candidate_original_title = (
            get_result_original_title(
                candidate,
                media_type
            )
        )

        normalized_candidate_title = (
            normalize_title(
                candidate_title
            )
        )

        normalized_candidate_original = (
            normalize_title(
                candidate_original_title
            )
        )

        # Exact match against either TMDB's
        # displayed title or original title.
        if (
            normalized_candidate_title
            == normalized_trakt_title
            or
            normalized_candidate_original
            == normalized_trakt_title
        ):

            candidate_year = get_result_year(
                candidate,
                media_type
            )

            # If the Trakt year is missing,
            # this isn't really a year mismatch.
            # However, it is still a legitimate
            # exact-title fallback.
            if not year:

                exact_candidates.append(
                    candidate
                )

            elif candidate_year:

                # We specifically want a different
                # year here.
                if candidate_year != year:

                    exact_candidates.append(
                        candidate
                    )

    # Only accept this fallback if there is
    # exactly ONE exact-title candidate.
    if len(exact_candidates) == 1:

        best = exact_candidates[0]

        mismatch_score = score_result(
            item,
            best
        )

        return {
            "result": best,
            "score": mismatch_score,
            "method": "title_exact_year_mismatch",
            "confidence": "medium",
        }

    # ----------------------------------------------
    # No match
    # ----------------------------------------------

    return None


# --------------------------------------------------
# Format TMDB result
# --------------------------------------------------

def format_tmdb_result(
    match
):
    """
    Convert the raw TMDB result into a compact
    structure for our output JSON.
    """

    result = match["result"]

    media_type = match.get(
        "media_type"
    )

    if media_type == "movie":

        title = (
            result.get("title")
            or result.get("original_title")
        )

        original_title = (
            result.get("original_title")
        )

        date = result.get(
            "release_date"
        )

    else:

        title = (
            result.get("name")
            or result.get("original_name")
        )

        original_title = (
            result.get("original_name")
        )

        date = result.get(
            "first_air_date"
        )

    return {

        "tmdb_id":
            result.get("id"),

        "tmdb_title":
            title,

        "tmdb_original_title":
            original_title,

        "tmdb_date":
            date,

        "tmdb_type":
            media_type,

        "tmdb_overview":
            result.get("overview"),

        "tmdb_poster_path":
            result.get("poster_path"),

        "tmdb_backdrop_path":
            result.get("backdrop_path"),

        "tmdb_vote_average":
            result.get("vote_average"),

        "tmdb_vote_count":
            result.get("vote_count"),

    }


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    print("=" * 60)
    print("TRAKT → TMDB MULTI-LIST SMART RESOLVER")
    print("=" * 60)
    print()

    # --------------------------------------------------
    # Load combined Trakt lists
    # --------------------------------------------------
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        trakt_items = json.load(f)

    print(f"Loaded {len(trakt_items)} list entries.")
    print()

    # --------------------------------------------------
    # Group duplicate media entries across lists.
    #
    # A title can appear in multiple Trakt lists. We only
    # resolve each unique (type, trakt_id) once, then attach
    # all of its list memberships to the resolved record.
    # --------------------------------------------------
    grouped = {}

    for item in trakt_items:
        trakt_id = item.get("trakt_id")
        media_type = item.get("type")

        # The scraper already skips incomplete cards, but keep
        # this guard here so a bad entry can never reach TMDB.
        if trakt_id is None or media_type is None:
            print(
                f"Skipping incomplete entry: {item.get('title')} "
                f"(type={media_type}, trakt_id={trakt_id})"
            )
            continue

        key = (media_type, trakt_id)

        if key not in grouped:
            grouped[key] = {
                **item,
                "lists": []
            }

        list_membership = {
            "list_name": item.get("list_name"),
            "list_slug": item.get("list_slug")
        }

        # Avoid duplicate list memberships if the scraper ever
        # produces the same item/list combination twice.
        if list_membership not in grouped[key]["lists"]:
            grouped[key]["lists"].append(list_membership)

    unique_items = list(grouped.values())

    print(f"Unique media items: {len(unique_items)}")
    print(f"Duplicate list entries collapsed: {len(trakt_items) - len(unique_items)}")
    print()

    resolved = []
    failed = []

    method_counts = {
        "title_year_exact": 0,
        "title_exact": 0,
        "title_normalized_year": 0,
        "title_normalized": 0,
        "title_variant_year": 0,
        "title_exact_year_mismatch": 0,
    }

    confidence_counts = {
        "high": 0,
        "medium": 0,
        "low": 0,
    }

    # --------------------------------------------------
    # Resolve each unique media item
    # --------------------------------------------------
    for index, item in enumerate(unique_items, start=1):
        print(
            f"[{index}/{len(unique_items)}] "
            f"{item['title']} "
            f"({item.get('year')}) "
            f"[{item['type']}] "
            f"— {len(item['lists'])} list(s)"
        )

        try:
            match = resolve_item(item)

            if match is None:
                print("  ❌ No reliable TMDB match")

                failed_item = {
                    **item,
                    "list_count": len(item["lists"]),
                    "tmdb": None
                }

                failed.append(failed_item)

            else:
                match["media_type"] = item["type"]

                tmdb = format_tmdb_result(match)

                method = match["method"]
                confidence = match["confidence"]
                score = match["score"]

                print(
                    f"  ✓ TMDB: {tmdb['tmdb_title']} "
                    f"(ID {tmdb['tmdb_id']})"
                )
                print(f"    Method: {method}")
                print(f"    Score: {score}")
                print(f"    Confidence: {confidence}")

                # Keep the first list's legacy list_name/list_slug
                # fields for easy compatibility, while also adding
                # the complete memberships array.
                resolved.append({
                    **item,
                    "list_count": len(item["lists"]),
                    "tmdb": {
                        **tmdb,
                        "match_method": method,
                        "match_score": score,
                        "match_confidence": confidence,
                    }
                })

                method_counts[method] += 1
                confidence_counts[confidence] += 1

        except Exception as e:
            print(f"  ❌ Error: {e}")

            failed.append({
                **item,
                "list_count": len(item["lists"]),
                "tmdb": None,
                "error": str(e)
            })

        # Small delay to avoid hammering TMDB.
        time.sleep(0.1)

    # --------------------------------------------------
    # Save combined resolved output
    # --------------------------------------------------
    # The /app/data directory may be a mounted volume, so the
    # nested /app/data/trakt directory is not guaranteed to exist.
    # Create it before writing the resolver output files.
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            resolved,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------
    # Save failures
    # --------------------------------------------------
    with open(FAILED_FILE, "w", encoding="utf-8") as f:
        json.dump(
            failed,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------
    # Build per-list outputs from the resolved data.
    # --------------------------------------------------
    by_list = {}

    for item in resolved:
        for membership in item.get("lists", []):
            slug = membership.get("list_slug")
            name = membership.get("list_name")

            if not slug:
                continue

            if slug not in by_list:
                by_list[slug] = {
                    "list_name": name,
                    "list_slug": slug,
                    "items": []
                }

            # Remove the aggregate lists array from the per-list
            # record so each list file is clean and self-contained.
            list_item = {
                **item,
                "list_name": name,
                "list_slug": slug,
            }
            list_item.pop("lists", None)
            list_item.pop("list_count", None)

            by_list[slug]["items"].append(list_item)

    os.makedirs("tmdb_lists", exist_ok=True)

    for slug, list_data in by_list.items():
        path = os.path.join(
            "tmdb_lists",
            f"{slug}.json"
        )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                list_data["items"],
                f,
                indent=2,
                ensure_ascii=False
            )

    # --------------------------------------------------
    # Summary
    # --------------------------------------------------
    print()
    print("=" * 60)
    print("TMDB MULTI-LIST RESOLUTION COMPLETE")
    print("=" * 60)
    print()

    print(f"List entries:       {len(trakt_items)}")
    print(f"Unique media:       {len(unique_items)}")
    print(f"TMDB matched:       {len(resolved)}")
    print(f"TMDB failed:        {len(failed)}")

    if unique_items:
        percentage = len(resolved) / len(unique_items) * 100
        print(f"Match rate:         {percentage:.1f}%")

    print()
    print(f"Lists found:        {len(by_list)}")
    print(f"Duplicate entries:  {len(trakt_items) - len(unique_items)}")

    # --------------------------------------------------
    # Media type statistics
    # --------------------------------------------------
    movie_count = sum(
        1 for item in resolved
        if item.get("type") == "movie"
    )
    show_count = sum(
        1 for item in resolved
        if item.get("type") == "show"
    )

    print()
    print("Matched media types:")
    print()
    print(f"  Movies:            {movie_count}")
    print(f"  Shows:             {show_count}")

    # --------------------------------------------------
    # Method statistics
    # --------------------------------------------------
    print()
    print("Match methods:")
    print()
    print(
        f"  Title + year exact:        "
        f"{method_counts['title_year_exact']}"
    )
    print(
        f"  Title exact:               "
        f"{method_counts['title_exact']}"
    )
    print(
        f"  Normalized title + year:   "
        f"{method_counts['title_normalized_year']}"
    )
    print(
        f"  Normalized title:          "
        f"{method_counts['title_normalized']}"
    )
    print(
        f"  Title variant + year:      "
        f"{method_counts['title_variant_year']}"
    )
    print(
        f"  Title exact + year mismatch: "
        f"{method_counts['title_exact_year_mismatch']}"
    )

    # --------------------------------------------------
    # Confidence statistics
    # --------------------------------------------------
    print()
    print("Confidence:")
    print()
    print(f"  High:    {confidence_counts['high']}")
    print(f"  Medium:  {confidence_counts['medium']}")
    print(f"  Low:     {confidence_counts['low']}")

    # --------------------------------------------------
    # Files
    # --------------------------------------------------
    print()
    print(f"Saved combined matches to: {OUTPUT_FILE}")
    print(f"Saved failures to:          {FAILED_FILE}")
    print("Saved per-list files to:    tmdb_lists/")

    # --------------------------------------------------
    # Per-list statistics
    # --------------------------------------------------
    if by_list:
        print()
        print("Per-list results:")
        print()

        for slug, list_data in by_list.items():
            movies = sum(
                1 for item in list_data["items"]
                if item.get("type") == "movie"
            )
            shows = sum(
                1 for item in list_data["items"]
                if item.get("type") == "show"
            )

            print(
                f"  {list_data['list_name']}"
            )
            print(
                f"    Items: {len(list_data['items'])} "
                f"(Movies: {movies}, Shows: {shows})"
            )
            print(
                f"    File: tmdb_lists/{slug}.json"
            )

    # --------------------------------------------------
    # Failed items
    # --------------------------------------------------
    if failed:
        print()
        print("Failed items:")
        print()

        for item in failed:
            print(
                f"  - {item['title']} "
                f"({item.get('year')}) "
                f"[{item['type']}] "
                f"— {len(item.get('lists', []))} list(s)"
            )


if __name__ == "__main__":
    main()
