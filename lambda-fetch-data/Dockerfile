FROM public.ecr.aws/lambda/python:3.10


WORKDIR /app

RUN yum install -y zip

# Copy requirements first (for Docker caching)
COPY requirements.txt .

# Install dependencies into /app
RUN pip install --upgrade pip
RUN pip install -r requirements.txt -t .

# Copy Lambda code
COPY src/ .

# Zip everything into a deployment package
RUN zip -r9 /app/deployment-package.zip .

