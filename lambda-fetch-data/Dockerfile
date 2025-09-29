FROM python:3.10-slim

WORKDIR /app

# Install zip utility (much faster on Ubuntu)
RUN apt-get update && apt-get install -y zip && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker caching)
COPY requirements.txt .

# Install dependencies into /app
RUN pip install --upgrade pip
RUN pip install -r requirements.txt -t .

# Copy Lambda code
COPY src/ .

# Create the deployment package in the expected location
RUN mkdir -p /asset && zip -r9 /asset/deployment-package.zip .

