# Project variables
PROJECT_ROOT := $(CURDIR)

# === Fetch Data Lambda (zip-based) ===
DIST_DIR := $(PROJECT_ROOT)/lambda-fetch-data/dist
ZIP_FILE := $(DIST_DIR)/deployment-package.zip
FUNCTION_NAME := fetch-fx-data

# === Process Data Lambda (image-based) ===
PROCESS_FUNCTION_NAME := process-fx-data

# === Run Inference Lambda (ECR-based) ===
INFERENCE_FUNCTION_NAME := run-inference
INFERENCE_ECR_REPO := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference

# AWS Configuration
AWS_ACCOUNT_ID := 852815611756
AWS_REGION := us-east-1
ECR_REPO := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/$(PROCESS_FUNCTION_NAME)

# IAM Role
LAMBDA_ROLE_ARN := arn:aws:iam::$(AWS_ACCOUNT_ID):role/graph-arbitrage-lambda-role

.PHONY: build clean deploy build-process deploy-process test-process test-fetch \
        build-inference deploy-inference test-inference clean-all help

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
# Run Inference Lambda (ECR-based)
# ------------------------------

# Build inference Lambda container image
# ------------------------------
# Run Inference Lambda (ECR-based)
# ------------------------------

# ------------------------------
# Run Inference Lambda (ECR-based, standalone)
# ------------------------------

INFERENCE_FUNCTION_NAME := run-inference
INFERENCE_ECR_REPO := $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference

build-inference:
	@echo "=== Building Run Inference Lambda container image ==="
	# Only build if requirements changed or image doesn't exist
	if [ "$$(find $(PROJECT_ROOT)/lambda-run-inference/requirements.txt -newer /tmp/last_inference_build 2>/dev/null)" ] || \
	   [ ! "$$(docker images -q graph-arbitrage-inference:latest 2>/dev/null)" ]; then \
		docker build -t graph-arbitrage-inference $(PROJECT_ROOT)/lambda-run-inference; \
		touch /tmp/last_inference_build; \
	fi
	@echo "✅ Build complete!"
deploy-inference: build-inference
	@echo "=== Deploying Run Inference Lambda as standalone container image ==="

	# Ensure ECR repository exists
	aws ecr describe-repositories --repository-names graph-arbitrage-inference || \
		aws ecr create-repository --repository-name graph-arbitrage-inference

	# Authenticate Docker to ECR
	aws ecr get-login-password --region $(AWS_REGION) | docker login \
		--username AWS --password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

	# Generate timestamp once and reuse it
	$(eval TIMESTAMP := $(shell date +%s))
	
	# Tag and push image
	docker tag graph-arbitrage-inference:latest $(INFERENCE_ECR_REPO):$(TIMESTAMP)
	docker push $(INFERENCE_ECR_REPO):$(TIMESTAMP)

	# Create or update Lambda
	if aws lambda get-function --function-name $(INFERENCE_FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing Lambda function..."; \
		aws lambda update-function-code \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--image-uri $(INFERENCE_ECR_REPO):$(TIMESTAMP); \
	else \
		echo "Creating new Lambda function..."; \
		aws lambda create-function \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--package-type Image \
			--role $(LAMBDA_ROLE_ARN) \
			--code ImageUri=$(INFERENCE_ECR_REPO):$(TIMESTAMP) \
			--timeout 300 \
			--memory-size 2048; \
	fi

	@echo "✅ Run Inference Deployment complete!"
test-inference:
	@echo "=== Testing Run Inference Lambda ==="
	aws lambda invoke \
		--function-name $(INFERENCE_FUNCTION_NAME) \
		--payload '{}' \
		response.json
	@echo "Lambda response:"
	cat response.json

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
# Test full pipeline
test-pipeline: test-fetch
	@sleep 10  # Wait for processing
	@make test-process
	@sleep 10  # Wait for inference
	@make test-inference

# ------------------------------
# Utility Targets
# ------------------------------

# View recent signals from DynamoDB
view-signals:
	@echo "=== Recent Trading Signals ==="
	aws dynamodb scan \
		--table-name fx-signals \
		--max-items 10 \
		--query "Items[*].{timestamp:timestamp, date:date, pair:signal_data.pair, action:signal_data.action, confidence:signal_data.confidence, predicted_return:signal_data.predicted_return}" \
		--output table

# Check Lambda status
status:
	@echo "=== Lambda Function Status ==="
	@for func in $(FUNCTION_NAME) $(PROCESS_FUNCTION_NAME) $(INFERENCE_FUNCTION_NAME); do \
		echo "Checking $$func..."; \
		aws lambda get-function --function-name $$func --query 'Configuration.{FunctionName:FunctionName, State:State, LastUpdateStatus:LastUpdateStatus}' 2>/dev/null || echo "$$func: Not found"; \
		echo ""; \
	done

# Clean everything
clean-all:
	rm -rf $(DIST_DIR)
	rm -f response.json test_event.json
	@echo "Clean complete"

# Help target
help:
	@echo "Available targets:"
	@echo ""
	@echo "=== Deployment Targets ==="
	@echo "  deploy              - Build and deploy fetch-fx-data Lambda (zip)"
	@echo "  deploy-process      - Build and deploy process-fx-data Lambda (container)"
	@echo "  deploy-inference    - Build and deploy run-inference Lambda (ECR container)"
	@echo "  deploy-inference-quick - Quick update of inference Lambda (no build)"
	@echo ""
	@echo "=== Test Targets ==="
	@echo "  test-fetch          - Test fetch-fx-data Lambda"
	@echo "  test-process        - Test process-fx-data Lambda"
	@echo "  test-inference      - Test run-inference Lambda and check signals"
	@echo "  test-pipeline       - Test full pipeline (fetch → process → inference)"
	@echo ""
	@echo "=== Utility Targets ==="
	@echo "  view-signals        - View recent trading signals from DynamoDB"
	@echo "  status              - Check status of all Lambda functions"
	@echo "  clean-all           - Clean all build artifacts"
	@echo "  help                - Show this help message"
