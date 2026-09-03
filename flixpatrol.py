#!/usr/bin/env python3

import json
import os
import re
import requests
from html import unescape
from html.parser import HTMLParser


class FlixPatrolParser(HTMLParser):
    """Parse FlixPatrol Top 10 pages into chart tables."""

    def __init__(self):
        super().__init__()
        self.current_heading = ""
        self.heading_text = ""
        self.in_heading = False
        self.heading_level = None
        self.in_table = False
        self.table_depth = 0
        self.current_link = None
        self.current_link_text = []
        self.tables = []
        self.current_table = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()

        if re.fullmatch(r"h[1-6]", tag):
            self.in_heading = True
            self.heading_level = tag
            self.heading_text = ""

        elif tag == "table":
            if not self.in_table:
                self.in_table = True
                self.table_depth = 1
                self.current_table = {
                    "heading": self.current_heading,
                    "links": [],
                }
                self.tables.append(self.current_table)
            else:
                self.table_depth += 1

        elif tag == "a" and self.in_table:
            href = attrs.get("href", "")
            if href.startswith("/title/"):
                self.current_link = href
                self.current_link_text = []

    def handle_endtag(self, tag):
        tag = tag.lower()

        if re.fullmatch(r"h[1-6]", tag):
            text = clean_text(self.heading_text)
            if text:
                self.current_heading = text
                self.headings.append({
                    "level": self.heading_level,
                    "text": text,
                })
            self.in_heading = False
            self.heading_level = None
            self.heading_text = ""

        elif tag == "table":
            if self.in_table:
                self.table_depth -= 1
                if self.table_depth == 0:
                    self.in_table = False
                    self.current_table = None

        elif tag == "a":
            if self.current_link and self.current_table:
                title = clean_text("".join(self.current_link_text))
                if title:
                    self.current_table["links"].append({
                        "url": self.current_link,
                        "title": title,
                    })
            self.current_link = None
            self.current_link_text = []

    def handle_data(self, data):
        if self.in_heading:
            self.heading_text += data
        if self.current_link:
            self.current_link_text.append(data)


def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return " ".join(text.split()).strip()


def fetch_with_flaresolverr(url, flaresolverr_url=None):
    flaresolverr_url = (
        flaresolverr_url
        or os.getenv(
            "FLARESOLVERR_URL",
            "http://192.168.50.140:8191/v1",
        )
    )

    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 120000,
    }

    response = requests.post(
        flaresolverr_url,
        json=payload,
        timeout=150,
    )

    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(
            "FlareSolverr returned: "
            + str(result.get("message") or result.get("status"))
        )

    html = result.get("solution", {}).get("response", "")

    if not html:
        raise RuntimeError("FlareSolverr returned no HTML")

    return html


def parse_page(html):
    parser = FlixPatrolParser()
    parser.feed(html)
    return parser


def find_chart(tables, keywords):
    for table in tables:
        heading = table["heading"].lower()
        if all(keyword.lower() in heading for keyword in keywords):
            links = table["links"]
            if len(links) >= 10:
                return links[:10]
    return []


def find_overall_chart(tables):
    # Prefer the primary "Top 10 Overall" chart and exclude
    # "Overall from Amazon Channels".
    for table in tables:
        heading = table["heading"].lower()
        if len(table["links"]) >= 10 and "overall" in heading:
            if "amazon" not in heading and "channel" not in heading:
                return table["links"][:10]

    # Fallback used by the working Canadian scraper.
    for table in tables:
        if len(table["links"]) >= 10:
            return table["links"][:10]

    return []


def format_results(links):
    return [
        {
            "rank": rank,
            "title": item["title"],
            "url": "https://flixpatrol.com" + item["url"],
        }
        for rank, item in enumerate(links[:10], 1)
    ]


class FlixPatrolCanada:
    """Reusable FlixPatrol Canadian chart scraper."""

    PLATFORMS = {
        "netflix": {
            "slug": "netflix",
            "name": "Netflix",
            "type": "movies_shows",
        },
        "disney-plus": {
            "slug": "disney",
            "name": "Disney+",
            "type": "movies_shows",
        },
        "prime-video": {
            "slug": "amazon-prime",
            "name": "Prime Video",
            "type": "movies_shows",
        },
        "apple-tv-plus": {
            "slug": "apple-tv",
            "name": "Apple TV+",
            "type": "movies_shows",
        },
        "paramount-plus": {
            "slug": "paramount-plus",
            "name": "Paramount+",
            "type": "movies_shows",
        },
        "crave": {
            "slug": "crave",
            "name": "Crave",
            "type": "overall",
        },
    }

    def __init__(self, logger=None, country="canada"):
        self.logger = logger
        self.country = country.lower()

    def _log(self, message, *args):
        if self.logger:
            self.logger.info(message, *args)
        else:
            print(message % args if args else message)

    def scrape_platform(self, platform, config):
        url = (
            f"https://flixpatrol.com/top10/"
            f"{config['slug']}/{self.country}/"
        )

        self._log("Fetching FlixPatrol: %s", url)
        html = fetch_with_flaresolverr(url)
        parser = parse_page(html)

        if config["type"] == "movies_shows":
            movies = find_chart(parser.tables, ["movie"])
            shows = find_chart(parser.tables, ["tv"])

            if len(movies) != 10:
                raise RuntimeError("Could not find the Movies chart")
            if len(shows) != 10:
                raise RuntimeError("Could not find the TV Shows chart")

            return {
                "name": config["name"],
                "platform": platform,
                "url": url,
                "type": "movies_shows",
                "movies": format_results(movies),
                "shows": format_results(shows),
            }

        if config["type"] == "overall":
            overall = find_overall_chart(parser.tables)
            if len(overall) != 10:
                raise RuntimeError(
                    "Could not find the Crave Overall chart"
                )

            return {
                "name": config["name"],
                "platform": platform,
                "url": url,
                "type": "overall",
                "overall": format_results(overall),
            }

        raise RuntimeError(
            f"Unknown platform type: {config['type']}"
        )

    def scrape(self):
        services = {}
        failures = {}

        for platform, config in self.PLATFORMS.items():
            try:
                services[platform] = self.scrape_platform(
                    platform,
                    config,
                )
            except Exception as exc:
                failures[platform] = str(exc)

        return {
            "source": "flixpatrol",
            "country": self.country.upper(),
            "services": services,
            "failures": failures,
        }
