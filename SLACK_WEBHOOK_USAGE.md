# Slack Webhook Usage Summary

## Overview
The code uses **Slack Incoming Webhooks** to send AWS billing reports and error notifications.

## Webhook Configuration

### Environment Variable
- **`SLACK_WEBHOOK_URL`**: The Slack Incoming Webhook URL
  - Format: `https://hooks.slack.com/services/xxx/yyy/zzzz`
  - Set via serverless parameter: `--param="slack_url=..."`

### Configuration Location
Defined in `serverless.yml`:
```yaml
environment:
  SLACK_WEBHOOK_URL: ${param:slack_url, ''}
```

## Usage in Code

### 1. Main Cost Report (handler.py:192-198)
```python
slack_hook_url = os.environ.get('SLACK_WEBHOOK_URL')
if slack_hook_url:
    user_ids_str = os.environ.get('SLACK_USER_IDS', '').strip()
    user_ids = [uid.strip() for uid in user_ids_str.split(',') if uid.strip()] if user_ids_str else []
    if not user_ids:
        user_ids = ['U06J131GL2U']  # Default fallback
    publish_slack(slack_hook_url, summary, buffer, recommendations, user_ids, data.get("total", 0))
```

### 2. Error Notifications (handler.py:217-232)
```python
slack_hook_url = os.environ.get('SLACK_WEBHOOK_URL')
if slack_hook_url:
    try:
        error_message = {
            "text": f"❌ *Error generating AWS cost report*\n\nError: {str(e)}",
            "blocks": [...]
        }
        requests.post(slack_hook_url, json=error_message, timeout=10)
    except Exception as slack_error:
        logger.error(f"Failed to send error notification to Slack: {str(slack_error)}")
```

## Webhook Type: Slack Incoming Webhooks

The code uses **Slack Incoming Webhooks**, which:
- ✅ Support Slack Block Kit formatting
- ✅ Simple POST requests with JSON payload
- ✅ No authentication tokens needed (webhook URL contains auth)
- ✅ One-way communication (send messages only)

### Payload Format
The `publish_slack()` function sends messages using Slack Block Kit format:

```python
payload = {
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "..."
            }
        },
        # ... more blocks
    ],
    "text": summary  # Fallback text for notifications
}
```

### HTTP Request
```python
requests.post(
    hook_url,
    json=payload,
    timeout=30,
    headers={'Content-Type': 'application/json'}
)
```

## Message Structure

### 1. Cost Report Messages Include:
- **Header**: User mentions + summary
- **Divider**: Visual separator
- **Cost Breakdown**: Formatted table
- **Recommendations** (if any): Cost optimization suggestions
- **Footer**: Timestamp

### 2. Error Messages Include:
- Error emoji and title
- Full error details in code block format

## Additional Slack Configuration

### User Mentions
- **Environment Variable**: `SLACK_USER_IDS`
- **Format**: Comma-separated user IDs (e.g., `U06J131GL2U,U07ABC123`)
- **Default**: `U06J131GL2U` if not provided
- **Usage**: Users are mentioned in the format `<@USER_ID>`

## Setup Instructions

1. **Create Slack Incoming Webhook**:
   - Go to https://api.slack.com/apps
   - Create a new app or use existing
   - Navigate to "Incoming Webhooks"
   - Activate incoming webhooks
   - Add new webhook to workspace
   - Copy the webhook URL

2. **Deploy with Webhook URL**:
   ```bash
   serverless deploy --stage="prod" \
     --param="slack_url=https://hooks.slack.com/services/xxx/yyy/zzzz"
   ```

## Notes

- The webhook URL is stored as an environment variable in Lambda
- Messages are sent asynchronously (no response handling needed)
- Error handling includes retry logic for failed webhook requests
- The webhook supports both plain text and Block Kit formatted messages
- Timeout is set to 30 seconds for regular messages, 10 seconds for error notifications

