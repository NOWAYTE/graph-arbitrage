# Use AWS Lambda Python 3.10 base image
FROM public.ecr.aws/lambda/python:3.10

# Set working directory
WORKDIR /var/task

# Copy requirements first for caching
COPY requirements.txt .

# Install dependencies (into the image, not zipped)
RUN pip install --no-cache-dir -r requirements.txt

# Copy your Lambda source code
COPY src/ .

# (Optional) if you have additional data/config files, copy them too
# COPY config/ ./config/

# Command for Lambda to run (your handler)
# Format: "file.function"
CMD ["lambda_function.lambda_handler"]

