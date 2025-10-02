# Project variables
PROJECT_ROOT := $(CURDIR)

# === Fetch Data Lambda (zip-based) ===
DIST_DIR := $(PROJECT_ROOT)/lambda-fetch-data/dist
ZIP_FILE := $(DIST_DIR)/deployment-package.zip
FUNCTION_NAME := fetch-fx-data

# === Process Data Lambda (image-based) ===
PROCESS_FUNCTION_NAME := process-fx-data
AWS_ACCOUNT_ID := 852815611756
AWS_REGION := us-east-1
ECR_REPO := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/$(PROCESS_FUNCTION_NAME)

# IAM Role
LAMBDA_ROLE_ARN := arn:aws:iam::$(AWS_ACCOUNT_ID):role/graph-arbitrage-lambda-role

.PHONY: build clean deploy build-process deploy-process test-process test-fetch clean-all help

# ------------------------------
# Fetch Data Lambda (zip-based)
# ------------------------------

# Clean old builds
clean:
	rm -rf $(DIST_DIR)

# Build deployment package inside Docker (fetch-data)
build: clean
	@echo "=== Building Fetch Data Lambda package in Docker ==="
	mkdir -p $(DIST_DIR)
	docker build -t lambda-builder $(PROJECT_ROOT)/lambda-fetch-data
	docker run --rm -v $(DIST_DIR):/out --entrypoint "" lambda-builder \
		cp /app/deployment-package.zip /out/
	@echo "=== Build complete: $(ZIP_FILE) ==="

# Deploy: build + upload + update/create lambda (fetch-data)
deploy: build
	@echo "=== Uploading to S3 ==="
	TIMESTAMP=$$(date +%s) && \
	aws s3 cp $(ZIP_FILE) s3://graph-arbitrage-lambda-deployments-$(AWS_ACCOUNT_ID)/fetch-fx-data/deployment-package-$$TIMESTAMP.zip && \
	if aws lambda get-function --function-name $(FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing function..."; \
		aws lambda update-function-code \
			--function-name $(FUNCTION_NAME) \
			--s3-bucket graph-arbitrage-lambda-deployments-$(AWS_ACCOUNT_ID) \
			--s3-key fetch-fx-data/deployment-package-$$TIMESTAMP.zip; \
	else \
		echo "Creating new function..."; \
		aws lambda create-function \
			--function-name $(FUNCTION_NAME) \
			--runtime python3.10 \
			--role $(LAMBDA_ROLE_ARN) \
			--handler lambda_function.lambda_handler \
			--code S3Bucket=graph-arbitrage-lambda-deployments-$(AWS_ACCOUNT_ID),S3Key=fetch-fx-data/deployment-package-$$TIMESTAMP.zip \
			--timeout 120 \
			--memory-size 256; \
	fi
	@echo "=== Deployment complete! ==="

# ------------------------------
# Process Data Lambda (container image)
# ------------------------------

# Build process-data Lambda container image
build-process:
	@echo "=== Building Process Data Lambda container image ==="
	docker build -t $(PROCESS_FUNCTION_NAME) $(PROJECT_ROOT)/lambda-process-data

# Deploy process-data Lambda as container image
deploy-process: build-process
	@echo "=== Deploying Process Data Lambda as container image ==="
	aws ecr describe-repositories --repository-names $(PROCESS_FUNCTION_NAME) || \
		aws ecr create-repository --repository-name $(PROCESS_FUNCTION_NAME)

	TIMESTAMP=$$(date +%s) && \
	aws ecr get-login-password --region $(AWS_REGION) | docker login \
		--username AWS \
		--password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com && \
	docker tag $(PROCESS_FUNCTION_NAME):latest $(ECR_REPO):$$TIMESTAMP && \
	docker push $(ECR_REPO):$$TIMESTAMP && \
	if aws lambda get-function --function-name $(PROCESS_FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing function..."; \
		aws lambda update-function-code \
			--function-name $(PROCESS_FUNCTION_NAME) \
			--image-uri $(ECR_REPO):$$TIMESTAMP; \
	else \
		echo "Creating new function..."; \
		aws lambda create-function \
			--function-name $(PROCESS_FUNCTION_NAME) \
			--package-type Image \
			--role $(LAMBDA_ROLE_ARN) \
			--code ImageUri=$(ECR_REPO):$$TIMESTAMP \
			--timeout 120 \
			--memory-size 256; \
	fi
	@echo "=== Process Data Deployment complete! ==="

# ------------------------------
# Test Targets
# ------------------------------

# Test process-data Lambda
test-process:
	@echo "=== Testing Process Data Lambda ==="
	aws lambda invoke \
		--function-name process-fx-data \
		--payload '{"Records":[{"s3":{"bucket":{"name":"graph-arbitrage-raw-data-se"},"object":{"key":"fx/2025-09-28_forex_rates.csv"}}}]}' \
		response.json
	@echo "Lambda response:"
	cat response.json

# Test fetch-data Lambda
test-fetch:
	@echo "=== Testing Fetch Data Lambda ==="
	aws lambda invoke \
		--function-name fetch-fx-data \
		--payload '{}' \
		response.json
	@echo "Lambda response:"
	cat response.json

# ------------------------------
# Utilities
# ------------------------------

# Clean everything
clean-all:
	rm -rf $(DIST_DIR)
	rm -f response.json test_event.json
	@echo "Clean complete"

# Help target
help:
	@echo "Available targets:"
	@echo "  deploy         - Build and deploy fetch-fx-data Lambda (zip)"
	@echo "  deploy-process - Build and deploy process-fx-data Lambda (container image)"
	@echo "  test-process   - Test process-fx-data Lambda with sample data"
	@echo "  test-fetch     - Test fetch-fx-data Lambda"
	@echo "  clean-all      - Clean all build artifacts"
	@echo "  help           - Show this help message"

