#!/bin/bash

# AWS Billing to Slack - Deployment and Test Script
set -e

echo "🚀 AWS Billing to Slack - Deployment Script"
echo "============================================"
echo ""

# Check if Slack webhook URL is provided
if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo "⚠️  SLACK_WEBHOOK_URL environment variable not set."
    echo "   You can deploy without it to test billing retrieval,"
    echo "   but messages won't be sent to Slack."
    echo ""
    read -p "Enter Slack webhook URL (or press Enter to skip): " SLACK_URL
    if [ -n "$SLACK_URL" ]; then
        export SLACK_WEBHOOK_URL="$SLACK_URL"
    fi
fi

# Check AWS credentials
echo "📋 Checking AWS credentials..."
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS credentials not configured. Please run 'aws configure' first."
    exit 1
fi

ACCOUNT_INFO=$(aws sts get-caller-identity)
ACCOUNT_ID=$(echo $ACCOUNT_INFO | grep -o '"Account": "[^"]*"' | cut -d'"' -f4)
echo "✅ AWS Account: $ACCOUNT_ID"
echo ""

# Build deployment parameters
DEPLOY_PARAMS=""
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    DEPLOY_PARAMS="--param=\"slack_url=$SLACK_WEBHOOK_URL\""
    echo "✅ Slack webhook URL configured"
else
    echo "⚠️  Deploying without Slack webhook (billing data will be retrieved but not sent)"
fi

# Optional: Slack user IDs
if [ -n "$SLACK_USER_IDS" ]; then
    DEPLOY_PARAMS="$DEPLOY_PARAMS --param=\"slack_user_ids=$SLACK_USER_IDS\""
    echo "✅ Slack user IDs configured: $SLACK_USER_IDS"
fi

echo ""
echo "📦 Deploying Lambda function..."
echo ""

# Deploy
if [ -n "$DEPLOY_PARAMS" ]; then
    eval "serverless deploy --stage=\"prod\" $DEPLOY_PARAMS"
else
    serverless deploy --stage="prod"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo ""
    echo "🧪 Testing Lambda function..."
    echo ""
    
    # Test the function
    if [ -n "$DEPLOY_PARAMS" ]; then
        eval "serverless invoke --function report_cost --stage=\"prod\" --log $DEPLOY_PARAMS"
    else
        serverless invoke --function report_cost --stage="prod" --log
    fi
    
    echo ""
    echo "✅ Test completed!"
    echo ""
    echo "📊 To view logs:"
    echo "   serverless logs --function report_cost --stage=prod --tail"
    echo ""
    echo "🔄 To invoke manually:"
    if [ -n "$DEPLOY_PARAMS" ]; then
        echo "   serverless invoke --function report_cost --stage=prod $DEPLOY_PARAMS"
    else
        echo "   serverless invoke --function report_cost --stage=prod"
    fi
else
    echo ""
    echo "❌ Deployment failed!"
    exit 1
fi

