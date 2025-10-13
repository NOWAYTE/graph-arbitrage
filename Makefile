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

# Build inference Lambda container image
build-inference:
	@echo "=== Building Run Inference Lambda container image ==="
	docker build -t graph-arbitrage-inference $(PROJECT_ROOT)/lambda-run-inference

# Deploy inference Lambda as container image
# Quick deploy inference (without build, uses latest image)
# ------------------------------
# Deploy Run Inference Lambda (wrapper over trainer image)
# ------------------------------
deploy-inference:
	@echo "=== Building Run Inference Lambda wrapper ==="
	# Ensure ECR repository exists
	aws ecr describe-repositories --repository-names graph-arbitrage-inference || \
		aws ecr create-repository --repository-name graph-arbitrage-inference

	# Build wrapper image on top of trainer
	docker build -t lambda-run-inference ./lambda-run-inference

	# Authenticate Docker to ECR
	aws ecr get-login-password --region $(AWS_REGION) | docker login \
		--username AWS --password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

	# Tag image with timestamp
	TIMESTAMP=$$(date +%s) && \
	docker tag lambda-run-inference:latest $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference:$$TIMESTAMP && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference:$$TIMESTAMP

	# Create or update Lambda
	if aws lambda get-function --function-name $(INFERENCE_FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing Lambda function..."; \
		aws lambda update-function-code \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--image-uri $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference:$$TIMESTAMP; \
	else \
		echo "Creating new Lambda function..."; \
		aws lambda create-function \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--package-type Image \
			--role $(LAMBDA_ROLE_ARN) \
			--code ImageUri=$(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-inference:$$TIMESTAMP \
			--timeout 300 \
			--memory-size 2048 \
			--environment Variables={"PYTORCH_ENABLE_MPS_FALLBACK"="1"}; \
	fi
	@echo "=== Run Inference Deployment complete! ==="

deploy-inference-quick:
	@echo "=== Quick Deploy Run Inference Lambda ==="
	TIMESTAMP=$$(date +%s) && \
	if aws lambda get-function --function-name $(INFERENCE_FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing function..."; \
		aws lambda update-function-code \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--image-uri 852815611756.dkr.ecr.us-east-1.amazonaws.com/graph-arbitrage-inference:latest; \
	else \
		echo "Function doesn't exist. Use 'make deploy-inference' instead."; \
		exit 1; \
	fi
	@echo "=== Quick Deployment complete! ==="

# Deploy run-inference Lambda using existing trainer image
deploy-inference-from-trainer:
	@echo "=== Deploy Run Inference Lambda from existing trainer image ==="
	@if aws lambda get-function --function-name $(INFERENCE_FUNCTION_NAME) 2>/dev/null; then \
		echo "Updating existing Lambda function..."; \
		aws lambda update-function-code \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--image-uri $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-trainer:latest; \
	else \
		echo "Creating new Lambda function pointing to trainer image..."; \
		aws lambda create-function \
			--function-name $(INFERENCE_FUNCTION_NAME) \
			--package-type Image \
			--role $(LAMBDA_ROLE_ARN) \
			--code ImageUri=$(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/graph-arbitrage-trainer:latest \
			--timeout 300 \
			--memory-size 2048 \
			--environment Variables={"PYTORCH_ENABLE_MPS_FALLBACK"="1"}; \
	fi
	@echo "=== Deployment from trainer image complete! ==="

# Deploy inference Lambda as container image

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

# Test inference Lambda
test-inference:
	@echo "=== Testing Run Inference Lambda ==="
	aws lambda invoke \
		--function-name run-inference \
		--payload '{}' \
		response.json
	@echo "Lambda response:"
	cat response.json
	
	@echo "=== Checking DynamoDB for signals ==="
	aws dynamodb scan --table-name fx-signals --max-items 5 --query "Items[*].{timestamp:timestamp, signal_id:signal_id, pair:signal_data.pair, action:signal_data.action, confidence:signal_data.confidence}"

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
