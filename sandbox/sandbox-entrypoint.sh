#!/bin/bash

# -------------------------------------------------------------------
# Start Redis (needed — JobFinder connects at require time)
# -------------------------------------------------------------------
if command -v redis-server &>/dev/null; then
    redis-server --daemonize yes --loglevel warning 2>/dev/null
    echo "Redis: started on :6379"
fi

# -------------------------------------------------------------------
# S3-based node_modules cache
#
# 1. Agent clones repo → watcher detects package-lock.json
# 2. Hash package-lock.json → check S3 for tarball
# 3. Cache hit  → download + extract (~30-60s)
# 4. Cache miss → npm install (~3 min), upload tarball to S3
#
# Works for ANY repo. No Docker image rebuild needed.
# -------------------------------------------------------------------

S3_BUCKET="${NPM_CACHE_BUCKET:-vahan-agent-cache}"
AWS_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

cache_node_modules() {
    while true; do
        for pkg_lock in /workspace/*/package-lock.json; do
            [ -f "$pkg_lock" ] || continue
            repo_dir=$(dirname "$pkg_lock")
            repo_name=$(basename "$repo_dir")
            modules="${repo_dir}/node_modules"

            # Skip if already installed
            [ -d "$modules" ] && continue

            # Avoid duplicate runs
            lock_file="${repo_dir}/.npm_cache_lock"
            [ -f "$lock_file" ] && continue
            touch "$lock_file"

            hash=$(sha256sum "$pkg_lock" | cut -c1-16)
            s3_key="s3://${S3_BUCKET}/node_modules/${repo_name}-${hash}.tar.gz"

            # Try S3 cache
            if aws s3 ls "$s3_key" --region "$AWS_REGION" >/dev/null 2>&1; then
                echo "=== S3 cache HIT: ${repo_name} (${hash}) ==="
                aws s3 cp "$s3_key" /tmp/nm-cache.tar.gz --region "$AWS_REGION" --quiet 2>/dev/null
                if [ $? -eq 0 ]; then
                    cd "$repo_dir" && tar xzf /tmp/nm-cache.tar.gz 2>/dev/null
                    rm -f /tmp/nm-cache.tar.gz
                    echo "=== Restored: $(du -sh "$modules" 2>/dev/null | cut -f1) ==="
                    continue
                fi
                echo "=== S3 download failed, falling back to npm install ==="
            else
                echo "=== S3 cache MISS: ${repo_name} (${hash}) ==="
            fi

            # Cache miss — npm install
            echo "=== npm install for ${repo_name} ==="
            cd "$repo_dir" && npm install 2>&1 | tail -5

            # Upload to S3 in background
            if [ -d "$modules" ]; then
                (cd "$repo_dir" \
                    && tar czf /tmp/nm-upload.tar.gz node_modules \
                    && aws s3 cp /tmp/nm-upload.tar.gz "$s3_key" --region "$AWS_REGION" --quiet 2>/dev/null \
                    && rm -f /tmp/nm-upload.tar.gz \
                    && echo "=== Cached to S3: ${repo_name} (${hash}) ===") &
            fi
        done
        sleep 2
    done
}
cache_node_modules &

# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------
export NODE_ENV="development"
export SENTRY_DSN=""
export ELASTIC_APM_ACTIVE="false"

echo "=== Sandbox ready ==="
echo "  Redis: localhost:6379"
echo "  S3 cache: s3://${S3_BUCKET}/node_modules/"
echo "=== Handing off to agent ==="

exec "$@"
