from pathlib import Path
from datetime import datetime, timezone
import json



class JSONExporter:
    def __init__(self, logger):
        self.logger = logger

    def export(
        self,
        provider,
        provider_display,
        media_type,
        country,
        items,
        name,
        source_url,
    ):
        output_dir = Path("data/output")
        output_dir.mkdir(parents=True, exist_ok=True)

        document = {
            "source": "flixpatrol",
            "provider": provider,
            "provider_display": provider_display,
            "country": country,
            "media_type": media_type,
            "name": name,
            "source_url": source_url,
            "updated": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }

        filename = f"{provider}-{media_type}-{country.lower()}.json"
        path = output_dir / filename

        path.write_text(
            json.dumps(
                document,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.logger.info("Exported %s", path)
        return path
