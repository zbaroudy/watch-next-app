# FlixPatrol Canada Top 10

A Dockerized Canadian streaming Top 10 application that combines FlixPatrol charts, TMDB matching/metadata, optional OMDb ratings, and a FastAPI web UI.

## Data flow

```text
FlixPatrol Canada
        ↓
FlareSolverr
        ↓
FlixPatrol chart parser
        ↓
TMDB title matching
        ↓
TMDB metadata
        ↓
JSON output
        ↓
FastAPI web UI
```

The application also includes a separate Trakt public-list workflow:

```text
Trakt public lists
        ↓
Playwright scraper
        ↓
TMDB resolver
        ↓
Resolved Trakt/TMDB data
        ↓
FastAPI web UI
```

## Canadian services

- Netflix — Top 10 Movies + Top 10 TV Shows
- Disney+ — Top 10 Movies + Top 10 TV Shows
- Prime Video — Top 10 Movies + Top 10 TV Shows
- Apple TV+ — Top 10 Movies + Top 10 TV Shows
- Paramount+ — Top 10 Movies + Top 10 TV Shows
- Crave — Top 10 Overall

Peacock and Max/HBO Max are intentionally excluded because the required Canadian FlixPatrol charts are not available.

## Requirements

- Docker / Docker Compose
- A TMDB API key
- A reachable FlareSolverr instance
- An optional OMDb API key for IMDb, Rotten Tomatoes, and Metacritic ratings

## Setup

1. Copy `.env.example` to `.env`.
2. Add your API keys and adjust the FlareSolverr URL if required.
3. Build and start the container:

```bash
docker compose build
docker compose up -d
```

The application runs an update immediately at startup and repeats according to `UPDATE_INTERVAL_HOURS`.

The web UI is exposed on port `8091` by the supplied Compose file.

## Trakt public lists

Edit `trakt_lists.json` to control which public Trakt lists are synchronized.

The scraper writes its intermediate files to `output/`. The resolver writes the final resolved data to:

```text
data/trakt/
```

The included list configuration is intentionally kept in source control; generated list data is runtime data and is ignored by Git.

## Runtime storage

The application generates these directories as needed:

```text
data/search/
data/metadata/
data/output/
data/omdb_cache/
data/trakt/
logs/
output/
```

These are runtime files and should not be committed to GitHub.

## Docker / Portainer

The repository is designed so that generated caches, logs, secrets, and output files are excluded from the Docker build context by `.dockerignore`.

The Compose file mounts the runtime directories as host volumes so updates and caches survive container recreation.

For Portainer, you can either deploy the included Compose stack from the repository or build the image from the repository.

## Important security note

Do not commit `.env` or API keys to GitHub. Use `.env.example` as the template and keep the real `.env` local to the deployment.
