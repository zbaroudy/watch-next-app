import threading
import time
import subprocess
import sys

import uvicorn

from config import load_config
from logger import setup_logger
from flixpatrol import FlixPatrolCanada
from exporter import JSONExporter
from tmdb import TMDBClient



PROVIDER_NAMES = {
    "netflix": "Netflix",
    "disney-plus": "Disney+",
    "prime-video": "Prime Video",
    "apple-tv-plus": "Apple TV+",
    "paramount-plus": "Paramount+",
    "crave": "Crave",
}


def run_web_server():
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )


def resolve_item(item, media_type, tmdb, logger):
    """Attach a TMDB match and metadata without failing the whole chart."""
    try:
        match = tmdb.resolve_title(
            title=item["title"],
            media_type=media_type,
            flixpatrol_url=item.get("url", ""),
        )

        item["tmdb_match"] = match

        if not match.get("matched") or not match.get("tmdb_id"):
            logger.warning(
                "TMDB match not found: %s",
                item["title"],
            )
            return

        item["tmdb_id"] = match["tmdb_id"]
        item["media_type"] = match["media_type"]

        if match.get("confidence") != "high":
            logger.warning(
                "TMDB %s confidence: %s -> %s",
                match.get("confidence", "unknown"),
                item["title"],
                match.get("matched_title"),
            )

        try:
            item["tmdb"] = tmdb.get_metadata(
                match["media_type"],
                match["tmdb_id"],
            )
        except Exception as exc:
            logger.warning(
                "TMDB metadata failed for %s (%s): %s",
                item["title"],
                item["tmdb_id"],
                exc,
            )

    except Exception as exc:
        logger.warning(
            "TMDB resolution failed for %s: %s",
            item["title"],
            exc,
        )
        item["tmdb_match"] = {
            "matched": False,
            "tmdb_id": None,
            "media_type": media_type,
            "confidence": "error",
            "error": str(exc),
        }


def process_service(service_key, service, tmdb, exporter, logger):
    provider_display = PROVIDER_NAMES.get(
        service_key,
        service.get("name", service_key),
    )

    if service["type"] == "movies_shows":
        charts = [
            (
                "movie",
                service["movies"],
                f"{provider_display} Movies Canada",
            ),
            (
                "tv",
                service["shows"],
                f"{provider_display} TV Shows Canada",
            ),
        ]
    else:
        charts = [
            (
                None,
                service["overall"],
                f"{provider_display} Top 10 Overall Canada",
            )
        ]

    for media_type, items, name in charts:
        logger.info(
            "Resolving %d titles: %s",
            len(items),
            name,
        )

        for item in items:
            resolve_item(
                item,
                media_type,
                tmdb,
                logger,
            )

        # Overall Crave items are mixed movie/TV. The item itself now
        # carries the resolved media_type.
        output_media_type = (
            "overall" if media_type is None else media_type
        )

        exporter.export(
            provider=service_key,
            provider_display=provider_display,
            media_type=output_media_type,
            country="CA",
            items=items,
            name=name,
            source_url=service["url"],
        )

def run_trakt_update(logger):
    """Run the complete Trakt -> TMDB update workflow."""

    logger.info("=" * 60)
    logger.info("Starting Trakt list update")
    logger.info("=" * 60)

    # -----------------------------------------------------
    # Step 1: Scrape all configured Trakt lists
    # -----------------------------------------------------

    logger.info("Running Trakt list scraper...")

    scraper = subprocess.run(
        [sys.executable, "/app/app/trakt_list_scraper.py"],
        capture_output=True,
        text=True,
    )

    if scraper.stdout:
        logger.info(
            "Trakt scraper output:\n%s",
            scraper.stdout,
        )

    if scraper.returncode != 0:
        logger.error(
            "Trakt scraper failed with exit code %d:\n%s",
            scraper.returncode,
            scraper.stderr,
        )
        return False

    logger.info("Trakt scraper completed successfully.")

    # -----------------------------------------------------
    # Step 2: Resolve Trakt items through TMDB
    # -----------------------------------------------------

    logger.info("Running TMDB resolver...")

    resolver = subprocess.run(
        [sys.executable, "/app/tmdb_resolver_multi.py"],
        capture_output=True,
        text=True,
    )

    if resolver.stdout:
        logger.info(
            "TMDB resolver output:\n%s",
            resolver.stdout,
        )

    if resolver.returncode != 0:
        logger.error(
            "TMDB resolver failed with exit code %d:\n%s",
            resolver.returncode,
            resolver.stderr,
        )
        return False

    logger.info("TMDB resolver completed successfully.")

    logger.info("=" * 60)
    logger.info("Trakt list update complete")
    logger.info("=" * 60)

    return True


def run_update(config, logger, fp_scraper, exporter, tmdb):
    logger.info("=" * 60)
    logger.info("Starting FlixPatrol Canada update")
    logger.info("=" * 60)

    dataset = fp_scraper.scrape()

    failures = dataset.get("failures", {})

    if failures:
        for service, error in failures.items():
            logger.error(
                "FlixPatrol failed: %s: %s",
                service,
                error,
            )

    for service_key, service in dataset["services"].items():
        try:
            process_service(
                service_key,
                service,
                tmdb,
                exporter,
                logger,
            )
        except Exception as exc:
            logger.exception(
                "Failed to process %s: %s",
                service_key,
                exc,
            )
    # -----------------------------------------------------
    # TRAKT LIST UPDATE
    # -----------------------------------------------------

    try:
        run_trakt_update(logger)

    except Exception as exc:
        logger.exception(
            "Trakt list update failed: %s",
            exc,
        )

    logger.info("=" * 60)
    logger.info(
        "FlixPatrol update complete: %d services succeeded, %d failed",
        len(dataset["services"]),
        len(failures),
    )
    logger.info("=" * 60)


def main():
    config = load_config()
    logger = setup_logger(config.log_level)

    logger.info("=" * 60)
    logger.info("%s", config.app_name)
    logger.info("Version          : %s", config.version)
    logger.info("Timezone         : %s", config.timezone)
    logger.info(
        "Update interval  : %s hours",
        config.update_interval_hours,
    )
    logger.info("=" * 60)

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True,
    )
    web_thread.start()

    logger.info("Web UI started on http://0.0.0.0:8000")

    fp_scraper = FlixPatrolCanada(
        logger=logger,
        country="canada",
    )
    exporter = JSONExporter(logger)
    tmdb = TMDBClient(
        config.tmdb_api_key,
        logger,
    )


    interval_seconds = config.update_interval_hours * 60 * 60

    # Run immediately on startup.
    run_update(
        config,
        logger,
        fp_scraper,
        exporter,
        tmdb,
    )

    while True:
        logger.info(
            "Next update in %s hours.",
            config.update_interval_hours,
        )
        time.sleep(interval_seconds)

        run_update(
            config,
            logger,
            fp_scraper,
            exporter,
            tmdb,
        )


if __name__ == "__main__":
    main()
