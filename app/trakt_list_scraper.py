import json
from pathlib import Path

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_FILE = "trakt_lists.json"

OUTPUT_DIR = Path("output")


# ============================================================
# TRAKT ID EXTRACTION
# ============================================================

def extract_trakt_id_from_image(image_url):
    """
    Extract Trakt media type and ID from a Trakt poster URL.

    Example:

    /images/movies/000/009/489/posters/...
        -> movie, 9489

    /images/shows/000/314/507/posters/...
        -> show, 314507
    """

    if not image_url:
        return None, None

    parts = image_url.split("/")

    try:
        media_index = parts.index("images")

        media_type_raw = parts[
            media_index + 1
        ]

        if media_type_raw not in (
            "movies",
            "shows"
        ):
            return None, None

        if len(parts) <= media_index + 4:
            return None, None

        a = parts[media_index + 2]
        b = parts[media_index + 3]
        c = parts[media_index + 4]

        if not (
            a.isdigit()
            and b.isdigit()
            and c.isdigit()
        ):
            return None, None

        trakt_id = int(
            a + b + c
        )

        media_type = (
            "movie"
            if media_type_raw == "movies"
            else "show"
        )

        return media_type, trakt_id

    except (
        ValueError,
        IndexError,
        TypeError,
        AttributeError
    ):
        return None, None


# ============================================================
# CARD EXTRACTION
# ============================================================

def extract_card_data(card):
    """
    Extract information from one populated Trakt card.
    """

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title_locator = card.locator(
        ".trakt-card-title"
    )

    if title_locator.count() == 0:
        return None

    title = (
        title_locator
        .first
        .inner_text(timeout=5000)
        .strip()
    )

    if not title:
        return None

    # --------------------------------------------------------
    # Subtitle
    # --------------------------------------------------------

    subtitle_locator = card.locator(
        ".trakt-card-subtitle"
    )

    subtitle = None

    if subtitle_locator.count():

        try:

            subtitle = (
                subtitle_locator
                .first
                .inner_text(timeout=3000)
                .strip()
            )

        except Exception:

            subtitle = None

    # --------------------------------------------------------
    # Tags
    # --------------------------------------------------------

    tag_locators = card.locator(
        ".trakt-text-tag p"
    )

    tags = []

    for i in range(
        tag_locators.count()
    ):

        try:

            text = (
                tag_locators
                .nth(i)
                .inner_text(timeout=2000)
                .strip()
            )

            if text:
                tags.append(text)

        except Exception:

            continue

    # --------------------------------------------------------
    # Year
    # --------------------------------------------------------

    year = None

    for tag in tags:

        if (
            len(tag) == 4
            and tag.isdigit()
            and 1900 <= int(tag) <= 2100
        ):

            year = int(tag)

            break

    # --------------------------------------------------------
    # Poster image
    # --------------------------------------------------------

    image_locator = card.locator(
        'img.trakt-card-cover-image'
        '[src*="media.trakt.tv"]'
    )

    image_url = None

    if image_locator.count():

        try:

            image_url = (
                image_locator
                .first
                .get_attribute(
                    "src",
                    timeout=3000
                )
            )

        except Exception:

            image_url = None

    # --------------------------------------------------------
    # Trakt ID + type
    # --------------------------------------------------------

    media_type, trakt_id = (
        extract_trakt_id_from_image(
            image_url
        )
    )

    return {
        "title": title,
        "subtitle": subtitle,
        "year": year,
        "type": media_type,
        "trakt_id": trakt_id,
        "tags": tags,
        "image_url": image_url,
    }


# ============================================================
# FIND CARD FOR TITLE
# ============================================================

def get_parent_card(title_locator):
    """
    Given a populated .trakt-card-title element,
    find its containing .trakt-card-content.

    This avoids extracting stale/recycled card
    containers that Trakt leaves in the DOM.
    """

    card = title_locator.locator(
        "xpath=ancestor::div[contains("
        "@class, 'trakt-card-content'"
        ")]"
    ).first

    return card


# ============================================================
# LOAD ALL LIST ITEMS
# ============================================================

def load_all_items(page):
    """
    Scroll through the Trakt list until no additional
    title elements appear.

    Uses .trakt-card-title as the authoritative count.
    """

    print()
    print("Loading list items...")

    previous_count = -1

    unchanged_rounds = 0

    max_unchanged_rounds = 8

    last_height = 0

    while True:

        # ----------------------------------------------------
        # Count actual populated titles
        # ----------------------------------------------------

        title_locator = page.locator(
            ".trakt-card-title"
        )

        current_count = (
            title_locator.count()
        )

        print(
            f"Loaded items: "
            f"{current_count}"
        )

        # ----------------------------------------------------
        # Check whether count changed
        # ----------------------------------------------------

        if current_count == previous_count:

            unchanged_rounds += 1

        else:

            unchanged_rounds = 0

        # ----------------------------------------------------
        # Get document height
        # ----------------------------------------------------

        try:

            current_height = page.evaluate(
                "document.body.scrollHeight"
            )

        except Exception:

            current_height = last_height

        # ----------------------------------------------------
        # If both the number of items AND page
        # height have stopped changing for several
        # rounds, we're probably at the end.
        # ----------------------------------------------------

        if (
            unchanged_rounds
            >= max_unchanged_rounds
        ):

            print(
                "No new items loading. "
                "Assuming end of list."
            )

            break

        previous_count = current_count

        last_height = current_height

        # ----------------------------------------------------
        # Scroll to the bottom
        # ----------------------------------------------------

        page.evaluate(
            """
            window.scrollTo(
                0,
                document.body.scrollHeight
            );
            """
        )

        # ----------------------------------------------------
        # Wait for lazy loading
        # ----------------------------------------------------

        page.wait_for_timeout(
            2500
        )

        # ----------------------------------------------------
        # Small additional scroll to trigger
        # virtualization/lazy loading.
        # ----------------------------------------------------

        page.mouse.wheel(
            0,
            1200
        )

        page.wait_for_timeout(
            1000
        )

    print()
    print(
        f"Finished loading "
        f"{current_count} items."
    )

    return current_count


# ============================================================
# SCRAPE ONE TRAKT LIST
# ============================================================

def scrape_trakt_list(
    browser,
    list_config
):

    list_name = list_config["name"]

    list_slug = list_config["slug"]

    trakt_url = list_config["url"]

    print()
    print("=" * 60)
    print(
        f"TRAKT LIST: {list_name}"
    )
    print("=" * 60)

    print()
    print(
        f"Slug: {list_slug}"
    )

    print()
    print(
        f"Opening:\n{trakt_url}\n"
    )

    page = browser.new_page(
        viewport={
            "width": 1920,
            "height": 1080
        }
    )

    try:

        # ----------------------------------------------------
        # Open page
        # ----------------------------------------------------

        page.goto(
            trakt_url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("Page loaded.")

        # Initial rendering delay.

        page.wait_for_timeout(
            4000
        )

        # ----------------------------------------------------
        # Load entire list
        # ----------------------------------------------------

        loaded_count = (
            load_all_items(page)
        )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT use:
        #
        # .trakt-card-content
        #
        # because Trakt can leave hundreds of stale
        # containers in the DOM.
        #
        # Instead, use the actual populated titles.
        # ----------------------------------------------------

        titles = page.locator(
            ".trakt-card-title"
        )

        title_count = titles.count()

        print()
        print(
            f"Found {title_count} "
            f"populated media titles."
        )

        results = []

        skipped = []

        seen_ids = set()

        print()
        print(
            "Extracting media information..."
        )

        # ----------------------------------------------------
        # Extract each actual populated title
        # ----------------------------------------------------

        for i in range(title_count):

            title_locator = titles.nth(i)

            try:

                title_text = (
                    title_locator
                    .inner_text(
                        timeout=5000
                    )
                    .strip()
                )

                if not title_text:

                    continue

                # ------------------------------------------------
                # Find its actual card
                # ------------------------------------------------

                card = get_parent_card(
                    title_locator
                )

                # ------------------------------------------------
                # Extract card data
                # ------------------------------------------------

                item = extract_card_data(
                    card
                )

                if item is None:

                    continue

                # ------------------------------------------------
                # Skip missing Trakt ID/type
                # ------------------------------------------------

                if (
                    item["trakt_id"]
                    is None
                    or
                    item["type"]
                    is None
                ):

                    skipped.append(
                        item
                    )

                    print(
                        f"Skipping: "
                        f"{item['title']}"
                    )

                    print(
                        f"  Type: "
                        f"{item['type']}"
                    )

                    print(
                        f"  Trakt ID: "
                        f"{item['trakt_id']}"
                    )

                    continue

                # ------------------------------------------------
                # Prevent duplicates
                #
                # Trakt's virtualized DOM can occasionally
                # expose the same item more than once.
                # ------------------------------------------------

                unique_key = (
                    item["type"],
                    item["trakt_id"]
                )

                if unique_key in seen_ids:

                    continue

                seen_ids.add(
                    unique_key
                )

                # ------------------------------------------------
                # Add list metadata
                # ------------------------------------------------

                item["list_name"] = (
                    list_name
                )

                item["list_slug"] = (
                    list_slug
                )

                results.append(
                    item
                )

            except Exception as e:

                print(
                    f"Error extracting "
                    f"title/card {i}: {e}"
                )

        # ----------------------------------------------------
        # Statistics
        # ----------------------------------------------------

        movies = [
            item
            for item in results
            if item["type"] == "movie"
        ]

        shows = [
            item
            for item in results
            if item["type"] == "show"
        ]

        print()
        print("=" * 60)
        print(
            f"LIST COMPLETE: "
            f"{list_name}"
        )
        print("=" * 60)

        print()

        print(
            f"Loaded titles:      "
            f"{loaded_count}"
        )

        print(
            f"Extracted valid:    "
            f"{len(results)}"
        )

        print(
            f"Movies:             "
            f"{len(movies)}"
        )

        print(
            f"Shows:              "
            f"{len(shows)}"
        )

        print(
            f"Skipped:            "
            f"{len(skipped)}"
        )

        return results, skipped

    finally:

        page.close()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(
        "TRAKT PUBLIC MULTI-LIST POC"
    )
    print("=" * 60)

    print()

    # --------------------------------------------------------
    # Load configuration
    # --------------------------------------------------------

    config_path = Path(
        CONFIG_FILE
    )

    if not config_path.exists():

        raise FileNotFoundError(
            f"Could not find "
            f"{CONFIG_FILE}"
        )

    with open(
        config_path,
        "r",
        encoding="utf-8"
    ) as f:

        lists = json.load(f)

    if not isinstance(
        lists,
        list
    ):

        raise ValueError(
            f"{CONFIG_FILE} must "
            f"contain a JSON array."
        )

    print(
        f"Configured lists: "
        f"{len(lists)}"
    )

    # --------------------------------------------------------
    # Create output directory
    # --------------------------------------------------------

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    # --------------------------------------------------------
    # Launch Chromium ONCE
    # --------------------------------------------------------

    with sync_playwright() as p:

        print()
        print(
            "Launching Chromium..."
        )

        browser = p.chromium.launch(
            headless=True
        )

        try:

            all_items = []

            all_skipped = []

            processed_lists = 0

            # ------------------------------------------------
            # Process each list
            # ------------------------------------------------

            for list_config in lists:

                required_keys = (
                    "name",
                    "slug",
                    "url"
                )

                if not all(
                    key in list_config
                    for key in required_keys
                ):

                    print()
                    print(
                        "Skipping invalid "
                        "list configuration:"
                    )

                    print(
                        json.dumps(
                            list_config,
                            indent=2
                        )
                    )

                    continue

                # ------------------------------------------------
                # Scrape
                # ------------------------------------------------

                results, skipped = (
                    scrape_trakt_list(
                        browser,
                        list_config
                    )
                )

                processed_lists += 1

                # ------------------------------------------------
                # Save individual list
                # ------------------------------------------------

                output_file = (
                    OUTPUT_DIR
                    / f"{list_config['slug']}.json"
                )

                with open(
                    output_file,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        results,
                        f,
                        indent=2,
                        ensure_ascii=False
                    )

                print()
                print(
                    f"Saved to: "
                    f"{output_file}"
                )

                # ------------------------------------------------
                # Combined output
                # ------------------------------------------------

                all_items.extend(
                    results
                )

                all_skipped.extend(
                    skipped
                )

            # ------------------------------------------------
            # Save combined output
            # ------------------------------------------------

            combined_file = (
                OUTPUT_DIR
                / "all_lists.json"
            )

            with open(
                combined_file,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    all_items,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            # ------------------------------------------------
            # Unique media statistics
            # ------------------------------------------------

            unique_items = {}

            for item in all_items:

                key = (
                    item["type"],
                    item["trakt_id"]
                )

                unique_items[key] = item

            # ------------------------------------------------
            # Overall statistics
            # ------------------------------------------------

            movies = [
                item
                for item in all_items
                if item["type"] == "movie"
            ]

            shows = [
                item
                for item in all_items
                if item["type"] == "show"
            ]

            print()
            print("=" * 60)
            print(
                "MULTI-LIST SCRAPE COMPLETE"
            )
            print("=" * 60)

            print()

            print(
                f"Lists configured:   "
                f"{len(lists)}"
            )

            print(
                f"Lists processed:    "
                f"{processed_lists}"
            )

            print(
                f"Total entries:      "
                f"{len(all_items)}"
            )

            print(
                f"Unique media:       "
                f"{len(unique_items)}"
            )

            print(
                f"Movies:             "
                f"{len(movies)}"
            )

            print(
                f"Shows:              "
                f"{len(shows)}"
            )

            print(
                f"Skipped:            "
                f"{len(all_skipped)}"
            )

            print()

            print(
                "Individual lists:"
            )

            for list_config in lists:

                output_file = (
                    OUTPUT_DIR
                    / f"{list_config['slug']}.json"
                )

                if output_file.exists():

                    print(
                        f"  {output_file}"
                    )

            print()

            print(
                "Combined:"
            )

            print(
                f"  {combined_file}"
            )

        finally:

            browser.close()


class TraktListSync:
    """Wrapper used by the main application scheduler."""

    def __init__(self, logger=None):
        self.logger = logger

    def run(self):
        config_path = Path(CONFIG_FILE)

        if not config_path.exists():
            raise FileNotFoundError(
                f"Could not find {CONFIG_FILE}"
            )

        with open(config_path, "r", encoding="utf-8") as f:
            lists = json.load(f)

        if not isinstance(lists, list):
            raise ValueError(
                f"{CONFIG_FILE} must contain a JSON array."
            )

        if self.logger:
            self.logger.info(
                "Starting Trakt sync for %d configured lists",
                len(lists),
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            try:
                for list_config in lists:
                    try:
                        scrape_trakt_list(
                            browser,
                            list_config,
                        )
                    except Exception as exc:
                        if self.logger:
                            self.logger.exception(
                                "Trakt list failed: %s: %s",
                                list_config.get("name", "Unknown"),
                                exc,
                            )
                        else:
                            print(
                                f"Trakt list failed: "
                                f"{list_config.get('name', 'Unknown')}: {exc}"
                            )
            finally:
                browser.close()

        if self.logger:
            self.logger.info("Trakt sync complete")

        return True

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()