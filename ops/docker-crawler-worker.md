# Docker scheduled crawler worker (Phase 25 P25.1)

Run the crawler as a long-lived daemon in its own container (one tick / hour):

```yaml
# add to docker-compose.local.yml
  crawler:
    build: ./backend
    container_name: umb-crawler
    restart: unless-stopped
    env_file: [.env]
    environment:
      LOCAL_POSTGRES_MODE: "true"
      LOCAL_POSTGRES_URL: postgresql://postgres:postgres@postgres:5432/umb
    depends_on:
      postgres: { condition: service_healthy }
    command: python -m app.crawl.crawler_scheduler --daemon --interval 3600
```

Or, for cron/systemd hosts, use `ops/crontab.example` / `ops/umb-crawler.{service,timer}`.
First run once: `python -m app.crawl.crawler_scheduler --reclassify` (tags archive=monthly).
