# Project variables
PROJECT_ROOT := $(CURDIR)
DIST_DIR := $(PROJECT_ROOT)/lambda-fetch-data/dist
ZIP_FILE := $(DIST_DIR)/deployment-package.zip
S3_BUCKET := graph-arbitrage-lambda-deployments-852815611756
FUNCTION_NAME := fetch-fx-data
TIMESTAMP := $(shell date +%s)
S3_KEY := fetch-fx-data/deployment-package-$(TIMESTAMP).zip

.PHONY: build clean deploy

# Clean old builds
clean:
	rm -rf $(DIST_DIR)

# Build deployment package inside Docker
build: clean
	@echo "=== Building Lambda package in Docker ==="
	mkdir -p $(DIST_DIR)
	docker build -t lambda-builder $(PROJECT_ROOT)/lambda-fetch-data
	docker run --rm -v $(DIST_DIR):/out --entrypoint "" lambda-builder \
		cp /app/deployment-package.zip /out/
	@echo "=== Build complete: $(ZIP_FILE) ==="

# Deploy: build + upload + update lambda
deploy: build
	@echo "=== Uploading to S3 ==="
	aws s3 cp $(ZIP_FILE) s3://$(S3_BUCKET)/$(S3_KEY)
	@echo "=== Updating Lambda $(FUNCTION_NAME) ==="
	aws lambda update-function-code \
		--function-name $(FUNCTION_NAME) \
		--s3-bucket $(S3_BUCKET) \
		--s3-key $(S3_KEY)
	@echo "=== Deployment complete! ==="

