FROM node:22-slim AS base

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# -------------------------------------------------------------------
# System dependencies + services
# -------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    gnupg2 \
    lsb-release \
    ca-certificates \
    build-essential \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# PostgreSQL 15
RUN echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-15 postgresql-client-15 \
    && rm -rf /var/lib/apt/lists/*

# Redis
RUN apt-get update && apt-get install -y --no-install-recommends redis-server \
    && rm -rf /var/lib/apt/lists/*

# RabbitMQ (via Erlang + RabbitMQ official repo)
RUN curl -fsSL https://github.com/rabbitmq/signing-keys/releases/download/3.0/rabbitmq-release-signing-key.asc \
    | gpg --dearmor -o /etc/apt/trusted.gpg.d/rabbitmq.gpg \
    && curl -fsSL https://github.com/rabbitmq/signing-keys/releases/download/3.0/cloudsmith.rabbitmq-erlang.E495BB49CC4BBE5B.key \
    | gpg --dearmor -o /etc/apt/trusted.gpg.d/rabbitmq-erlang.gpg \
    && echo "deb https://ppa1.novemberain.com/rabbitmq/rabbitmq-erlang/deb/debian $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/rabbitmq-erlang.list \
    && echo "deb https://ppa1.novemberain.com/rabbitmq/rabbitmq-server/deb/debian $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/rabbitmq.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends erlang-base rabbitmq-server \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------------
# GitHub CLI
# -------------------------------------------------------------------
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------------
# Global Node tools
# -------------------------------------------------------------------
RUN npm install -g eslint prettier mocha

# -------------------------------------------------------------------
# PostgreSQL: initialize cluster + create test user/db
# -------------------------------------------------------------------
USER postgres
RUN /usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/15/main \
    && /usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/15/main -l /tmp/pg.log start \
    && psql --command "CREATE USER test WITH SUPERUSER PASSWORD 'test';" \
    && createdb -O test testdb \
    && /usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/15/main stop
USER root

# -------------------------------------------------------------------
# Workspace setup
# -------------------------------------------------------------------
WORKDIR /workspace

# -------------------------------------------------------------------
# Entrypoint: start services, then hand off to CMD
# -------------------------------------------------------------------
COPY sandbox-entrypoint.sh /sandbox-entrypoint.sh
RUN chmod +x /sandbox-entrypoint.sh

ENTRYPOINT ["/sandbox-entrypoint.sh"]
CMD ["bash"]
