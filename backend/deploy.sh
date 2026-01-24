#!/usr/bin/env bash
set -euo pipefail

# ShadowPartner Backend Remote Deploy Script
# Usage: ./deploy.sh user@host /srv/shadowpartner/data [/path/to/.env.prod]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
IMAGE_NAME="shadowpartner-backend"
CONTAINER_NAME="shadowpartner-backend"

# Parse arguments
REMOTE_HOST="${1:-}"
DATA_PATH="${2:-}"
ENV_FILE="${3:-$BACKEND_DIR/.env.production}"

# Validate arguments
if [[ -z "$REMOTE_HOST" || -z "$DATA_PATH" ]]; then
    echo "Usage: $0 <user@host> <data-path> [env-file]"
    echo ""
    echo "  user@host    Remote SSH destination (e.g., root@192.168.1.100)"
    echo "  data-path    Required: Absolute path for data volume (e.g., /srv/shadowpartner/data)"
    echo "  env-file     Optional: Path to env file (default: backend/.env.production)"
    echo ""
    echo "Example:"
    echo "  $0 root@192.168.1.100 /srv/shadowpartner/data"
    echo "  $0 root@192.168.1.100 /srv/shadowpartner/data .env.production"
    exit 1
fi

# Check env file exists
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: Env file not found: $ENV_FILE"
    echo "Create it from .env.example:"
    echo "  cp backend/.env.example backend/.env.production"
    echo "  # Edit .env.production with your values"
    exit 1
fi

echo "==> ShadowPartner Backend Remote Deploy"
echo "    Host: $REMOTE_HOST"
echo "    Data: $DATA_PATH"
echo "    Env:  $ENV_FILE"
echo ""

# # Run tests
# echo "==> Running tests..."
# cd "$PROJECT_ROOT"
# if [[ -f "$BACKEND_DIR/pyproject.toml" ]]; then
#     cd "$BACKEND_DIR"
#     uv run pytest tests/ -q || {
#         echo "Tests failed. Abort deploy."
#         exit 1
#     }
# fi

# Build image
echo "==> Building Docker image..."
docker build -t "$IMAGE_NAME" "$BACKEND_DIR"

# Ensure remote data directory exists
echo "==> Setting up remote directories..."
ssh "$REMOTE_HOST" "mkdir -p '$DATA_PATH/storage'"

# Copy env file to remote
echo "==> Copying env file..."
REMOTE_ENV="/tmp/shadowpartner-backend-env-\$\$"
scp "$ENV_FILE" "$REMOTE_HOST:$REMOTE_ENV"

# Stop and remove old container
echo "==> Stopping old container..."
ssh "$REMOTE_HOST" "docker stop '$CONTAINER_NAME' 2>/dev/null || true"
ssh "$REMOTE_HOST" "docker rm '$CONTAINER_NAME' 2>/dev/null || true"

# Transfer image
echo "==> Transfering image..."
docker save "$IMAGE_NAME" | ssh "$REMOTE_HOST" "docker load"

# Remove old image to save space (keep current)
ssh "$REMOTE_HOST" "docker images '$IMAGE_NAME' --format '{{.ID}}' | tail -n +2 | xargs -r docker rmi -f 2>/dev/null || true"

# Run new container
echo "==> Starting container..."
ssh "$REMOTE_HOST" "
    docker run -d \\
        --name '$CONTAINER_NAME' \\
        --restart=unless-stopped \\
        --network=host \\
        -p 127.0.0.1:8000:8000 \\
        -v '$DATA_PATH:/app/data' \\
        -v /tmp:/tmp:rw \\
        --env-file '$REMOTE_ENV' \\
        --health-cmd='curl -f http://localhost:8000/health || exit 1' \\
        --health-interval=30s \\
        --health-timeout=10s \\
        --health-retries=3 \\
        '$IMAGE_NAME'
"

# Cleanup env file
ssh "$REMOTE_HOST" "rm -f '$REMOTE_ENV'"

# Wait for health check
echo "==> Waiting for container to be healthy..."
sleep 5
for i in {1..30}; do
    if ssh "$REMOTE_HOST" "docker inspect --format='{{.State.Health.Status}}' '$CONTAINER_NAME' 2>/dev/null | grep -q healthy"; then
        echo "    Container is healthy!"
        break
    fi
    if ssh "$REMOTE_HOST" "docker inspect --format='{{.State.Status}}' '$CONTAINER_NAME' 2>/dev/null | grep -q running"; then
        echo "    Container is running (waiting for health check)..."
        sleep 2
    else
        echo "    Container not running. Check logs:"
        ssh "$REMOTE_HOST" "docker logs '$CONTAINER_NAME' --tail 50"
        exit 1
    fi
done

echo ""
echo "==> Deploy complete!"
echo ""
echo "Check status:"
echo "  ssh $REMOTE_HOST docker logs -f '$CONTAINER_NAME'"
echo ""
echo "Health check:"
echo "  ssh $REMOTE_HOST docker inspect --format='{{.State.Health.Status}}' '$CONTAINER_NAME'"
