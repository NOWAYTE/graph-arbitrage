FROM 852815611756.dkr.ecr.us-east-1.amazonaws.com/graph-arbitrage-trainer:latest

# Copy inference-specific code
COPY src/ /app/inference/

# Set Python path to include inference code
ENV PYTHONPATH=/app:/app/inference

# Add __init__.py so inference is a package
RUN touch /app/inference/__init__.py

# Set Lambda handler
CMD ["inference.lambda_function.lambda_handler"]

