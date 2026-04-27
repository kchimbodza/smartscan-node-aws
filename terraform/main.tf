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

# ── Variables ─────────────────────────────────────────────────────────────────
variable "aws_region"  { default = "us-east-1" }
variable "thing_name"  { default = "smartscan-node-aws-01" }
variable "alert_email" { description = "Email for SNS occupancy alerts" }

# ── DynamoDB Table ────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "occupancy" {
  name         = "smartscan-occupancy"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"
  range_key    = "timestamp"

  attribute {
    name = "device_id"
    type = "S"
  }
  attribute {
    name = "timestamp"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Project = "SmartScanNode" }
}

# ── SNS Topic ─────────────────────────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "smartscan-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── IAM Role for Lambda ───────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_role" {
  name = "smartscan-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "smartscan-lambda-policy"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
        Resource = aws_dynamodb_table.occupancy.arn
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# ── Lambda Function ───────────────────────────────────────────────────────────
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/presence_handler.py"
  output_path = "${path.module}/presence_handler.zip"
}

resource "aws_lambda_function" "presence_handler" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "smartscan-presence-handler"
  role             = aws_iam_role.lambda_role.arn
  handler          = "presence_handler.lambda_handler"
  runtime          = "python3.12"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.occupancy.name
      SNS_TOPIC_ARN  = aws_sns_topic.alerts.arn
      ALERT_ENABLED  = "true"
    }
  }

  tags = { Project = "SmartScanNode" }
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.presence_handler.function_name}"
  retention_in_days = 14
}

# ── IoT Core Thing ────────────────────────────────────────────────────────────
resource "aws_iot_thing" "node" {
  name = var.thing_name
}

resource "aws_iot_policy" "node_policy" {
  name = "smartscan-node-aws-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive"]
      Resource = "*"
    }]
  })
}

# ── IoT Rule → Lambda ─────────────────────────────────────────────────────────
resource "aws_iot_topic_rule" "presence_rule" {
  name        = "smartscan_presence_rule"
  enabled     = true
  sql         = "SELECT * FROM 'smartscan/presence'"
  sql_version = "2016-03-23"

  lambda {
    function_arn = aws_lambda_function.presence_handler.arn
  }
}

resource "aws_lambda_permission" "iot_invoke" {
  statement_id  = "AllowIoTInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presence_handler.function_name
  principal     = "iot.amazonaws.com"
  source_arn    = aws_iot_topic_rule.presence_rule.arn
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "dynamodb_table"    { value = aws_dynamodb_table.occupancy.name }
output "lambda_function"   { value = aws_lambda_function.presence_handler.function_name }
output "sns_topic_arn"     { value = aws_sns_topic.alerts.arn }
output "iot_thing_name"    { value = aws_iot_thing.node.name }
