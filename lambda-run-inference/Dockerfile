# Use the AWS Lambda Python 3.10 base image
FROM public.ecr.aws/lambda/python:3.10

# Set working directory
WORKDIR /var/task

# Copy function code
COPY src/ /var/task/

# Install dependencies if present
# (You can add a requirements.txt in src/ if needed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || true

# Command for Lambda to run
CMD ["lambda_function.lambda_handler"]

