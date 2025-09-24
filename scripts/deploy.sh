#!/usr/bin/env bash
set -e

echo "Deploying Lambda function..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

# Build the deployment package using Docker
echo "Building deployment package with Docker..."
docker build -t lambda-builder "$PROJECT_ROOT"
docker run --rm -v "$PROJECT_ROOT":/out lambda-builder

# Set variables
TIMESTAMP=$(date +%s)
ZIP_PATH="${PROJECT_ROOT}/output/deployment-package.zip"
S3_BUCKET="graph-arbitrage-lambda-deployments-852815611756"
S3_KEY="fetch-fx-data/deployment-package-${TIMESTAMP}.zip"

# Upload to S3
echo "Uploading package to S3..."
aws s3 cp "$ZIP_PATH" "s3://${S3_BUCKET}/${S3_KEY}"

# Update Lambda function
echo "Updating Lambda function..."
aws lambda update-function-code \
  --function-name fetch-fx-data \
  --s3-bucket $S3_BUCKET \
  --s3-key $S3_KEY

echo "Deployment complete! Lambda function updated."

