FROM node:22-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps + git + redis + native module build tools + runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates gnupg2 lsb-release python3 \
    redis-server \
    # Build tools for native modules (bcrypt, canvas, pg-native)
    build-essential pkg-config \
    # Canvas build + runtime deps
    libcairo2-dev libpango1.0-dev libjpeg-dev libpng-dev libgif-dev \
    # PostgreSQL build + runtime deps
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Global Node tools
RUN npm install -g eslint prettier mocha

# AWS CLI (for S3 npm cache)
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && apt-get update && apt-get install -y --no-install-recommends unzip \
    && cd /tmp && unzip -q awscliv2.zip && ./aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && apt-get purge -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY sandbox-entrypoint.sh /sandbox-entrypoint.sh
RUN chmod +x /sandbox-entrypoint.sh

CMD ["sleep", "7200"]
