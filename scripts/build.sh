#!/bin/bash

set -e

echo "Building Lambda deployment package..."

cd lambda-fetch-data

# Build the Docker image
docker build -t lambda-builder .

# Create a container and copy the deployment package
docker create --name lambda-container lambda-builder
docker cp lambda-container:/asset/deployment-package.zip ./
docker rm lambda-container

echo "Build complete! deployment-package.zip is ready."
