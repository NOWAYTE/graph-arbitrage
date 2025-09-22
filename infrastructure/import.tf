
resource "aws_s3_bucket" "raw_data" {
  bucket = "graph-arbitrage-raw-data-se"
}

resource "aws_s3_bucket" "processed_data" {
  bucket = "graph-arbitrage-processed-data-se"
}

resource "aws_dynamodb_table" "fx_signals" {
  name         = "fx-signals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "timestamp"

  attribute {
    name = "timestamp"
    type = "N"
  }
}

resource "aws_lambda_function" "fetch_data" {
  function_name = "fetch-fx-data"
  # Other attributes will be filled in by the import
}