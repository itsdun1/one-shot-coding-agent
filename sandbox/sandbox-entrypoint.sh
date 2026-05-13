#!/bin/bash
set -e

# -------------------------------------------------------------------
# Start PostgreSQL
# -------------------------------------------------------------------
su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/15/main -l /var/log/postgresql/pg.log start"

# Wait for PostgreSQL to accept connections
until pg_isready -q -h localhost -p 5432 -U test; do
    sleep 0.5
done

# -------------------------------------------------------------------
# Start Redis
# -------------------------------------------------------------------
redis-server --daemonize yes --loglevel warning

# Wait for Redis
until redis-cli ping 2>/dev/null | grep -q PONG; do
    sleep 0.5
done

# -------------------------------------------------------------------
# Start RabbitMQ
# -------------------------------------------------------------------
rabbitmq-server -detached 2>/dev/null || true

# Wait for RabbitMQ (up to 15 seconds)
for i in $(seq 1 30); do
    if rabbitmqctl status >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

# -------------------------------------------------------------------
# Export environment variables for the agent
# -------------------------------------------------------------------
export DATABASE_URL="postgresql://test:test@localhost:5432/testdb"
export REDIS_URL="redis://localhost:6379"
export RABBITMQ_URL="amqp://localhost:5672"
export NODE_ENV="testing"
export PGUSER="test"
export PGPASSWORD="test"
export PGDATABASE="testdb"
export PGHOST="localhost"
export PGPORT="5432"

echo "=== Sandbox services ready ==="
echo "  PostgreSQL: localhost:5432 (user=test, db=testdb)"
echo "  Redis:      localhost:6379"
echo "  RabbitMQ:   localhost:5672"
echo "=== Handing off to agent ==="

# Hand off to whatever command the sandbox provider passes
exec "$@"
