# Deployment Information

## Deployment Region

**Current Region: `us-east-1` (N. Virginia)**

The function is deployed to `us-east-1` based on the following priority:

1. **Environment Variable**: `AWS_REGION` (if set)
2. **Environment Variable**: `AWS_DEFAULT_REGION` (if set)
3. **Default**: `us-east-1` (as specified in `serverless.yml` line 25)

Since neither `AWS_REGION` nor `AWS_DEFAULT_REGION` were set during deployment, it defaulted to `us-east-1`.

### To Deploy to a Different Region:

```bash
# Option 1: Set environment variable
export AWS_REGION=eu-west-1
serverless deploy --stage="prod"

# Option 2: Set during deployment
AWS_REGION=eu-west-1 serverless deploy --stage="prod"

# Option 3: Modify serverless.yml default region
```

## Environment Variables Source

Environment variables are set in the Lambda function from **three sources** (in priority order):

### 1. Serverless Parameters (Highest Priority)
Set during deployment using `--param` flags:

```bash
serverless deploy --stage="prod" \
  --param="slack_url=https://hooks.slack.com/..." \
  --param="slack_user_ids=U06HQU9040Z" \
  --param="group=SERVICE" \
  --param="group_length=10"
```

These map to environment variables in `serverless.yml`:
- `${param:slack_url, ''}` → `SLACK_WEBHOOK_URL`
- `${param:slack_user_ids, ''}` → `SLACK_USER_IDS`
- `${param:group, 'SERVICE'}` → `GROUP_BY`
- `${param:group_length, 10}` → `LENGTH`

### 2. Environment Variables in serverless.yml
Defined in `serverless.yml` lines 60-71:

```yaml
environment:
  GROUP_BY: ${param:group, 'SERVICE'}
  LENGTH: ${param:group_length, 10}
  SLACK_WEBHOOK_URL: ${param:slack_url, ''}
  SLACK_USER_IDS: ${param:slack_user_ids, ''}
  # ... etc
```

### 3. Code-Level Environment Variables (Lowest Priority)
The handler code reads from `os.environ`:

```python
group_by = os.environ.get("GROUP_BY", "SERVICE")
length = int(os.environ.get("LENGTH", "10"))
slack_hook_url = os.environ.get('SLACK_WEBHOOK_URL')
```

## Current Environment Variables

As of last deployment, the Lambda function has:

```json
{
  "GROUP_BY": "SERVICE",
  "LENGTH": "10",
  "SLACK_WEBHOOK_URL": "",  // ⚠️ Not set - needs to be configured
  "SLACK_USER_IDS": "U06HQU9040Z",  // ✅ Set
  "TEAMS_WEBHOOK_URL": "",
  "GOOGLE_WEBHOOK_URL": "",
  "AWS_ACCOUNT_NAME": "",
  "CREDITS_EXPIRE_DATE": "",
  "CREDITS_REMAINING_AS_OF": "",
  "CREDITS_REMAINING": "",
  "COST_AGGREGATION": "UnblendedCost"
}
```

## How to Update Environment Variables

### Method 1: Redeploy with Parameters (Recommended)
```bash
serverless deploy --stage="prod" \
  --param="slack_url=YOUR_WEBHOOK_URL" \
  --param="slack_user_ids=U06HQU9040Z"
```

### Method 2: Update via AWS Console
1. Go to AWS Lambda Console
2. Select function: `aws-billing-to-slack-prod-report_cost`
3. Go to Configuration → Environment variables
4. Edit/add variables

### Method 3: Update via AWS CLI
```bash
aws lambda update-function-configuration \
  --function-name aws-billing-to-slack-prod-report_cost \
  --environment "Variables={SLACK_WEBHOOK_URL=https://hooks.slack.com/...}"
```

## Function Details

- **Function Name**: `aws-billing-to-slack-prod-report_cost`
- **Region**: `us-east-1`
- **Account**: `528104389666`
- **ARN**: `arn:aws:lambda:us-east-1:528104389666:function:aws-billing-to-slack-prod-report_cost`
- **Memory**: 256 MB
- **Timeout**: 30 seconds
- **Runtime**: Python 3.10
- **Schedule**: Daily at 15:00 UTC (10am CDT)

## Important Notes

1. **Cost Explorer API**: The function uses AWS Cost Explorer API which is only available in `us-east-1` and `us-west-2`. Since we're using `us-east-1`, this is correct.

2. **Environment Variables Persist**: Once set via deployment, they persist until the next deployment or manual update.

3. **Parameter Syntax**: Serverless Framework uses `${param:name, 'default'}` syntax where:
   - `param:name` = parameter name from `--param="name=value"`
   - `'default'` = fallback value if parameter not provided

