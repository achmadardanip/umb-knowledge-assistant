# evaluation/promptfoo/scheduler/Dockerfile
FROM node:20-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-requests cron ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Pre-cache the pinned promptfoo CLI
RUN npx --yes promptfoo@0.121.17 --version || true

COPY run-eval.sh /usr/local/bin/run-eval.sh
COPY crontab /etc/cron.d/promptfoo-eval
RUN chmod +x /usr/local/bin/run-eval.sh \
 && chmod 0644 /etc/cron.d/promptfoo-eval \
 && crontab /etc/cron.d/promptfoo-eval

# The repo is mounted at /work (see docker-compose). cron runs in the foreground.
WORKDIR /work/evaluation/promptfoo
CMD ["cron", "-f"]
