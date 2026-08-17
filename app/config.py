from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass
class AppConfig:
    app_name: str
    version: str
    log_level: str
    timezone: str
    tmdb_api_key: str
    flaresolverr_url: str
    update_interval_hours: float


def load_config() -> AppConfig:
    tmdb_api_key = os.getenv("TMDB_API_KEY", "").strip()

    if not tmdb_api_key:
        raise ValueError(
            "TMDB_API_KEY is missing from the .env file."
        )

    try:
        update_interval_hours = float(
            os.getenv("UPDATE_INTERVAL_HOURS", "6")
        )
    except ValueError as exc:
        raise ValueError(
            "UPDATE_INTERVAL_HOURS must be a number."
        ) from exc

    if update_interval_hours <= 0:
        raise ValueError(
            "UPDATE_INTERVAL_HOURS must be greater than 0."
        )

    return AppConfig(
        app_name=os.getenv(
            "APP_NAME",
            "FlixPatrol Canada Top 10",
        ),
        version=os.getenv(
            "APP_VERSION",
            "1.0.0",
        ),
        log_level=os.getenv(
            "LOG_LEVEL",
            "INFO",
        ),
        timezone=os.getenv(
            "TZ",
            "America/Toronto",
        ),
        tmdb_api_key=tmdb_api_key,
        flaresolverr_url=os.getenv(
            "FLARESOLVERR_URL",
            "http://192.168.50.140:8191/v1",
        ),
        update_interval_hours=update_interval_hours,
    )
