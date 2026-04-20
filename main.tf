terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "tu-bucket-terraform-state"
    key    = "ecobici-infra.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "ecobici_bucket" {
  bucket = "tu-bucket-aqui"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ecobici_bucket" {
  bucket = aws_s3_bucket.ecobici_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_lambda_function" "ingest_lambda" {
  filename         = "ingest.zip"
  function_name    = "ecobici-ingest"
  role            = aws_iam_role.lambda_exec.arn
  handler          = "ingest.lambda_handler"
  source_code_hash = filebase64sha256("ingest.zip")
  runtime         = "python3.9"
  timeout         = 30
  memory_size      = 128
  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.ecobici_bucket.bucket
    }
  }
}

resource "aws_lambda_function" "inference_lambda" {
  function_name    = "ecobici-inference"
  role            = aws_iam_role.lambda_exec.arn
  package_type    = "Image"
  image_uri       = "tu-account-id.dkr.ecr.us-east-1.amazonaws.com/ecobici-inference:latest"
  timeout         = 60
  memory_size     = 512
  environment {
    variables = {
      MODEL_BUCKET = aws_s3_bucket.ecobici_bucket.bucket
      LOG_BUCKET  = aws_s3_bucket.ecobici_bucket.bucket
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "lambda_exec_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_cloudwatch_event_rule" "every_15_minutes" {
  name           = "ecobici-ingest-schedule"
  description   = "Ejecuta cada 15 minutos"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "ingest_lambda_target" {
  rule      = aws_cloudwatch_event_rule.every_15_minutes.target[0]
  target_id = "ecobici-ingest-lambda"
  arn       = aws_lambda_function.ingest_lambda.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_15_minutes.arn
}

resource "aws_apigatewayv2_api" "lambda_api" {
  name                         = "ecobici-inference-api"
  protocol_type                = "HTTP"
  route_key                   = "POST /predict"
  target                      = aws_lambda_function.inference_lambda.arn
}

resource "aws_apigatewayv2_stage" "default" {
  api_id = aws_apigatewayv2_api.lambda_api.id
  name   = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id           = aws_apigatewayv2_api.lambda_api.id
  integration_uri  = aws_lambda_function.inference_lambda.arn
  integration_type = "AWS_PROXY"
}