output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.lambda_function.lambda_function_arn
}

output "s3_bucket_lambda_deployments_arn" {
  description = "ARN of the S3 bucket for Lambda deployments"
  value       = aws_s3_bucket.lambda_deployments.arn
}

output "s3_bucket_raw_data_arn" {
  description = "ARN of the S3 bucket for raw data"
  value       = aws_s3_bucket.raw_data.arn
}

output "s3_bucket_processed_data_arn" {
  description = "ARN of the S3 bucket for processed data"
  value       = aws_s3_bucket.processed_data.arn
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table"
  value       = aws_dynamodb_table.fx_signals.arn
}
