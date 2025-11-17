#!/bin/bash

# Configuration - Docker Hub registry
DOCKER_REGISTRY="${DOCKER_REGISTRY:-amiroz}"      # Your Docker Hub username
PUSH_IMAGE="${PUSH_IMAGE:-true}"                   # Enable push by default

# Generate unique build identifiers
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BUILD_ID=$(openssl rand -hex 4)
GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")

# Create unique tag combining timestamp, git hash, and random build ID
if [ -n "$DOCKER_REGISTRY" ]; then
    UNIQUE_TAG="${DOCKER_REGISTRY}/projects:stock_insights_${TIMESTAMP}_${GIT_HASH}_${BUILD_ID}"
    LATEST_TAG="${DOCKER_REGISTRY}/projects:stock_insights_latest"
else
    UNIQUE_TAG="projects:stock_insights_${TIMESTAMP}_${GIT_HASH}_${BUILD_ID}"
    LATEST_TAG="projects:stock_insights_latest"
fi

# Multi-platform build (Intel + ARM64)
PLATFORM="linux/amd64,linux/arm64"

echo "🏗️  Building stock insights Docker image with unique tag: ${UNIQUE_TAG}"
echo "🚀 Platform: ${PLATFORM} (Multi-platform: Intel + ARM64)"

# Build multi-platform image using buildx
docker buildx create --use --name multiarch-builder 2>/dev/null || docker buildx use multiarch-builder

docker buildx build \
    --platform "${PLATFORM}" \
    --build-arg BUILD_TIMESTAMP="${TIMESTAMP}" \
    --build-arg BUILD_ID="${BUILD_ID}" \
    --build-arg GIT_HASH="${GIT_HASH}" \
    --no-cache \
    -t "${UNIQUE_TAG}" \
    -t "${LATEST_TAG}" \
    --push \
    .

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Docker image built and pushed successfully!"
    echo "🏷️  Unique tag: ${UNIQUE_TAG}"
    echo "🏷️  Latest tag: ${LATEST_TAG}"
    echo "🚀 Platform: ${PLATFORM} (Multi-platform)"
    echo "🌐 Registry: Docker Hub (${DOCKER_REGISTRY})"
    echo ""
    echo "✅ Images pushed to Docker Hub:"
    echo "   - ${UNIQUE_TAG}"
    echo "   - ${LATEST_TAG}"
    
    echo ""
    echo "You can now run it with:"
    echo "  docker run --env-file .env ${UNIQUE_TAG} --date 10-11-2025 --env prod"
    echo "  docker run --env-file .env ${LATEST_TAG} --date 10-11-2025 --env dev"
    echo ""
    echo "Or use it in your Airflow DAG as '${UNIQUE_TAG}'"
else
    echo "❌ Docker build failed!"
    exit 1
fi

