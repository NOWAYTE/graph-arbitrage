variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource tagging"
  type        = string
  default     = "graph-arbitrage"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "fetch-fx-data"
}

variable "s3_bucket_lambda_deployments" {
  description = "S3 bucket for Lambda deployments"
  type        = string
  default     = "graph-arbitrage-lambda-852815611756"
}

variable "s3_bucket_raw_data" {
  description = "S3 bucket for raw data"
  type        = string
  default     = "graph-arbitrage-raw-data-se"
}

variable "s3_bucket_processed_data" {
  description = "S3 bucket for processed data"
  type        = string
  default     = "graph-arbitrage-processed-data-se"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table for signals"
  type        = string
  default     = "fx-signals"
}
