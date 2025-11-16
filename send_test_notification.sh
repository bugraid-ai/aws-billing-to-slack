#!/bin/bash

# Send Test Billing Notification to Slack
set -e

SLACK_WEBHOOK_URL="${1:-$SLACK_WEBHOOK_URL}"
USER_ID="U06HQU9040Z"

if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo "❌ Error: Slack webhook URL is required"
    echo ""
    echo "Usage:"
    echo "  ./send_test_notification.sh https://hooks.slack.com/services/xxx/yyy/zzzz"
    echo ""
    echo "Or set environment variable:"
    echo "  export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzzz"
    echo "  ./send_test_notification.sh"
    echo ""
    echo "To get your webhook URL:"
    echo "  1. Go to https://api.slack.com/apps"
    echo "  2. Select your app (or create a new one)"
    echo "  3. Go to 'Incoming Webhooks'"
    echo "  4. Activate and create a webhook for your channel"
    echo "  5. Copy the webhook URL"
    exit 1
fi

echo "🚀 Deploying with Slack webhook and user ID..."
echo "   User ID: $USER_ID"
echo ""

# Deploy with webhook URL and user ID
serverless deploy --stage="prod" \
  --param="slack_url=$SLACK_WEBHOOK_URL" \
  --param="slack_user_ids=$USER_ID" \
  2>&1 | tail -10

echo ""
echo "📤 Sending test billing notification to Slack..."
echo ""

# Invoke the function to send test notification
serverless invoke --function report_cost --stage="prod" --log

echo ""
echo "✅ Test notification sent! Check your Slack channel."
echo ""

