resource "aws_iam_role" "lambda_role" {
  name = "${var.function_name}-role"

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
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.function_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.s3_bucket_raw_data_arn,
          "${var.s3_bucket_raw_data_arn}/*",
          var.s3_bucket_processed_data_arn,
          "${var.s3_bucket_processed_data_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Scan"
        ]
        Resource = var.dynamodb_table_arn
      }
    ]
  })
}

resource "aws_lambda_function" "lambda_function" {
  function_name = var.function_name
  role          = aws_iam_role.lambda_role.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size

  # The S3 bucket and key for the Lambda deployment package will be passed in
  s3_bucket = var.s3_bucket_lambda_deployments
  s3_key    = var.s3_key

  environment {
    variables = var.environment_variables
  }
}

resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 14
}
