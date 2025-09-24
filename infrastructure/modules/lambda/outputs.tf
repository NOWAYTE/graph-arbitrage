output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.lambda_function.arn
}

output "lambda_role_arn" {
  description = "ARN of the IAM role for the Lambda function"
  value       = aws_iam_role.lambda_role.arn
}
