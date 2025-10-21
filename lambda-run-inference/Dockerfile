# Use the AWS Lambda Python 3.10 base image
FROM public.ecr.aws/lambda/python:3.10

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements first (for caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy your function code
COPY src/ ${LAMBDA_TASK_ROOT}

# Set the Lambda handler
CMD ["lambda_function.lambda_handler"]

