terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# S3 Bucket for Lambda deployments
resource "aws_s3_bucket" "lambda_deployments" {
  bucket = "graph-arbitrage-lambda-${var.account_id}"

  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_versioning" "lambda_deployments" {
  bucket = aws_s3_bucket.lambda_deployments.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Bucket for raw data
resource "aws_s3_bucket" "raw_data" {
  bucket = "graph-arbitrage-raw-data-se"

  tags = {
    Project = var.project_name
  }
}

# S3 Bucket for processed data
resource "aws_s3_bucket" "processed_data" {
  bucket = "graph-arbitrage-processed-data-se"

  tags = {
    Project = var.project_name
  }
}

# DynamoDB table for signals
resource "aws_dynamodb_table" "fx_signals" {
  name         = "fx-signals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "timestamp"

  attribute {
    name = "timestamp"
    type = "N"
  }

  tags = {
    Project = var.project_name
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "graph-arbitrage-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project = var.project_name
  }
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "lambda_policy" {
  name = "graph-arbitrage-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.raw_data.arn,
          "${aws_s3_bucket.raw_data.arn}/*",
          aws_s3_bucket.processed_data.arn,
          "${aws_s3_bucket.processed_data.arn}/*",
          aws_s3_bucket.lambda_deployments.arn,
          "${aws_s3_bucket.lambda_deployments.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Scan"
        ]
        Resource = aws_dynamodb_table.fx_signals.arn
      }
    ]
  })
}
