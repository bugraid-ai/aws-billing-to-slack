from collections import defaultdict
import boto3
import datetime
import os
import requests
import sys
import json
import logging
from typing import Dict, List, Tuple, Optional
from botocore.exceptions import ClientError, BotoCoreError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

n_days = 7
today = datetime.datetime.today()
yesterday = today - datetime.timedelta(days=1)
week_ago = today - datetime.timedelta(days=n_days)

# It seems that the sparkline symbols don't line up (probably based on font?) so put them last
# Also, leaving out the full block because Slack doesn't like it: '█'
sparks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇']

# Cost thresholds for recommendations (in USD)
HIGH_COST_THRESHOLD = 100.0  # Daily cost threshold for high-cost services
SIGNIFICANT_INCREASE_THRESHOLD = 20.0  # Percentage increase threshold
EC2_COST_THRESHOLD = 50.0  # EC2 cost threshold for recommendations
LAMBDA_COST_THRESHOLD = 10.0  # Lambda cost threshold for recommendations


def sparkline(datapoints):
    """Generate a sparkline visualization from datapoints."""
    if not datapoints or all(d == 0 for d in datapoints):
        return "▁" * len(datapoints)
    
    lower = min(datapoints)
    upper = max(datapoints)
    n_sparks = len(sparks) - 1

    line = ""
    for dp in datapoints:
        scaled = 1 if upper == 0 else dp/upper
        which_spark = round(scaled * n_sparks)
        line += (sparks[which_spark])

    return line


def delta(costs):
    """Calculate percentage change between last two days."""
    if len(costs) > 1 and costs[-1] >= 1 and costs[-2] >= 1:
        result = ((costs[-1]/costs[-2])-1)*100.0
    else:
        result = 0
    return result


def find_by_key(values: list, key: str, value: str):
    """Find an item in a list by key-value match."""
    for item in values:
        if item.get(key) == value:
            return item
    return None


def get_detailed_ec2_breakdown(client, yesterday_date: str) -> Dict[str, float]:
    """Get detailed breakdown of EC2 - Other costs by instance type and usage type."""
    try:
        # Query for EC2 costs by INSTANCE_TYPE
        # Note: EC2 - Other typically includes costs not categorized under specific instance types
        instance_type_query = {
            "TimePeriod": {
                "Start": yesterday_date,
                "End": (datetime.datetime.strptime(yesterday_date, '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            },
            "Granularity": "DAILY",
            "Filter": {
                "And": [
                    {
                        "Dimensions": {
                            "Key": "SERVICE",
                            "Values": [
                                "Amazon Elastic Compute Cloud - Compute",
                                "EC2 - Other"
                            ]
                        }
                    },
                    {
                        "Not": {
                            "Dimensions": {
                                "Key": "RECORD_TYPE",
                                "Values": ["Credit", "Refund", "Upfront", "Support"]
                            }
                        }
                    }
                ]
            },
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
                {"Type": "DIMENSION", "Key": "USAGE_TYPE"}
            ],
        }
        
        result = client.get_cost_and_usage(**instance_type_query)
        breakdown = {}
        
        for day in result.get('ResultsByTime', []):
            for group in day.get('Groups', []):
                instance_type = group['Keys'][0] if len(group['Keys']) > 0 else "Unknown"
                usage_type = group['Keys'][1] if len(group['Keys']) > 1 else "Unknown"
                cost = float(group['Metrics']['UnblendedCost']['Amount'])
                
                key = f"{instance_type} ({usage_type})"
                breakdown[key] = breakdown.get(key, 0) + cost
        
        return breakdown
    except Exception as e:
        logger.warning(f"Failed to get detailed EC2 breakdown: {str(e)}")
        return {}


def get_cost_recommendations(service_costs: List[Tuple[str, List[float]]], total_cost: float, detailed_ec2_breakdown: Dict[str, float] = None) -> List[str]:
    """Generate cost reduction recommendations based on spending patterns."""
    recommendations = []
    
    # Analyze top services
    for service_name, costs in service_costs[:10]:  # Top 10 services
        daily_cost = costs[-1] if costs else 0.0
        cost_increase = delta(costs)
        
        # EC2 recommendations with detailed breakdown
        if "EC2" in service_name or "Elastic Compute Cloud" in service_name:
            if daily_cost > EC2_COST_THRESHOLD:
                recommendations.append(
                    f"• *EC2 ({service_name})*: Consider using Reserved Instances or Savings Plans "
                    f"for predictable workloads. Current daily cost: ${daily_cost:,.2f}"
                )
                if cost_increase > SIGNIFICANT_INCREASE_THRESHOLD:
                    recommendations.append(
                        f"  → EC2 costs increased by {cost_increase:.1f}%. Review instance types and sizes."
                    )
                
                # Add detailed EC2 breakdown if available
                if detailed_ec2_breakdown and "EC2 - Other" in service_name:
                    top_ec2_items = sorted(detailed_ec2_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]
                    if top_ec2_items:
                        recommendations.append(f"  *EC2 - Other Breakdown (Top 5):*")
                        for item, cost in top_ec2_items:
                            if cost > 1.0:  # Only show items costing more than $1
                                recommendations.append(f"    - {item}: ${cost:,.2f}")
        
        # Lambda recommendations
        if "Lambda" in service_name:
            if daily_cost > LAMBDA_COST_THRESHOLD:
                recommendations.append(
                    f"• *Lambda*: Review function duration and memory allocation. "
                    f"Consider optimizing cold starts. Current daily cost: ${daily_cost:,.2f}"
                )
        
        # RDS recommendations
        if "RDS" in service_name or "Relational Database" in service_name:
            if daily_cost > HIGH_COST_THRESHOLD:
                recommendations.append(
                    f"• *RDS ({service_name})*: Consider Reserved Instances for production databases. "
                    f"Review instance sizes and storage. Current daily cost: ${daily_cost:,.2f}"
                )
        
        # S3 recommendations
        if "S3" in service_name or "Simple Storage" in service_name:
            if daily_cost > HIGH_COST_THRESHOLD:
                recommendations.append(
                    f"• *S3*: Review storage classes (move to Glacier/Deep Archive for old data). "
                    f"Check for incomplete multipart uploads. Current daily cost: ${daily_cost:,.2f}"
                )
        
        # CloudWatch recommendations
        if "CloudWatch" in service_name:
            if daily_cost > 20.0:
                recommendations.append(
                    f"• *CloudWatch*: Review log retention periods and custom metrics. "
                    f"Consider reducing log volume. Current daily cost: ${daily_cost:,.2f}"
                )
        
        # Data Transfer recommendations
        if "Data Transfer" in service_name or "Bandwidth" in service_name:
            if daily_cost > 30.0:
                recommendations.append(
                    f"• *Data Transfer*: Review data transfer patterns. Consider using CloudFront "
                    f"or optimizing cross-region transfers. Current daily cost: ${daily_cost:,.2f}"
                )
        
        # General high-cost service recommendations
        if daily_cost > HIGH_COST_THRESHOLD and cost_increase > SIGNIFICANT_INCREASE_THRESHOLD:
            recommendations.append(
                f"• *{service_name}*: Costs increased by {cost_increase:.1f}% (${daily_cost:,.2f}/day). "
                f"Review usage patterns and consider optimization."
            )
    
    # General recommendations based on total cost
    if total_cost > 500:
        recommendations.append(
            "• *Overall*: Consider setting up AWS Budgets with alerts to monitor spending."
        )
        recommendations.append(
            "• *Overall*: Review AWS Cost Explorer for detailed cost analysis and trends."
        )
    
    if total_cost > 1000:
        recommendations.append(
            "• *Overall*: Consider engaging AWS Support for a Well-Architected Review to optimize costs."
        )
    
    # Remove duplicates while preserving order
    seen = set()
    unique_recommendations = []
    for rec in recommendations:
        if rec not in seen:
            seen.add(rec)
            unique_recommendations.append(rec)
    
    return unique_recommendations[:10]  # Limit to top 10 recommendations


def retry_api_call(func, max_retries=3, *args, **kwargs):
    """Retry an API call with exponential backoff."""
    import time
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except (ClientError, BotoCoreError) as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Unexpected error in API call: {str(e)}")
            raise


def lambda_handler(event, context):
    """Main Lambda handler function."""
    try:
        group_by = os.environ.get("GROUP_BY", "SERVICE")
        length = int(os.environ.get("LENGTH", "10"))
        cost_aggregation = os.environ.get("COST_AGGREGATION", "UnblendedCost")
        
        logger.info(f"Starting cost report generation for group_by={group_by}, length={length}")
        
        summary, buffer, data, recommendations, detailed_ec2, report_date = report_cost(
            group_by=group_by, 
            length=length, 
            cost_aggregation=cost_aggregation
        )
        
        # Log billing data for verification
        logger.info(f"Billing Summary: {summary}")
        logger.info(f"Total Cost: ${data.get('total', 0):,.2f}")
        logger.info(f"Cost Breakdown:\n{buffer}")
        if recommendations:
            logger.info(f"Recommendations generated: {len(recommendations)}")

        slack_hook_url = os.environ.get('SLACK_WEBHOOK_URL', '').strip()
        logger.info(f"Slack webhook URL configured: {'Yes' if slack_hook_url else 'No'}")
        if slack_hook_url:
            user_ids_str = os.environ.get('SLACK_USER_IDS', '').strip()
            mention_here = os.environ.get('SLACK_MENTION_HERE', 'false').lower() == 'true'
            user_ids = [uid.strip() for uid in user_ids_str.split(',') if uid.strip()] if user_ids_str else []
            if not user_ids and not mention_here:
                user_ids = ['U06HQU9040Z']  # Default fallback
            logger.info(f"Sending to Slack: webhook={'configured'}, user_ids={user_ids}, mention_here={mention_here}")
            publish_slack(slack_hook_url, summary, buffer, recommendations, user_ids, data.get("total", 0), mention_here, report_date)
        else:
            logger.warning("SLACK_WEBHOOK_URL not configured - skipping Slack notification")

        teams_hook_url = os.environ.get('TEAMS_WEBHOOK_URL')
        if teams_hook_url:
            publish_teams(teams_hook_url, summary, buffer)
        
        google_hook_url = os.environ.get('GOOGLE_WEBHOOK_URL')
        if google_hook_url:
            publish_google(google_hook_url, summary, buffer)
        
        logger.info("Cost report successfully generated and sent")
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Cost report sent successfully'})
        }
    
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        # Try to send error notification to Slack if webhook is available
        slack_hook_url = os.environ.get('SLACK_WEBHOOK_URL')
        if slack_hook_url:
            try:
                error_message = {
                    "text": f"❌ *Error generating AWS cost report*\n\nError: {str(e)}",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"❌ *Error generating AWS cost report*\n\n```{str(e)}```"
                            }
                        }
                    ]
                }
                requests.post(slack_hook_url, json=error_message, timeout=10)
            except Exception as slack_error:
                logger.error(f"Failed to send error notification to Slack: {str(slack_error)}")
        
        raise


def report_cost(
    group_by: str = "SERVICE", 
    length: int = 5, 
    cost_aggregation: str = "UnblendedCost", 
    result: dict = None, 
    yesterday: str = None, 
    new_method: bool = True
) -> Tuple[str, str, Dict, List[str]]:
    """Generate cost report from AWS Cost Explorer API."""
    
    if yesterday is None:
        yesterday = today - datetime.timedelta(days=1)
    else:
        yesterday = datetime.datetime.strptime(yesterday, '%Y-%m-%d')

    week_ago = today - datetime.timedelta(days=n_days)
    # Generate list of dates, so that even if our data is sparse,
    # we have the correct length lists of costs (len is n_days)
    list_of_dates = [
        (week_ago + datetime.timedelta(days=x)).strftime('%Y-%m-%d')
        for x in range(n_days)
    ]

    # Get account name from env, or account id/account alias from boto3
    account_name = os.environ.get("AWS_ACCOUNT_NAME", "").strip()
    if not account_name:
        try:
            iam = boto3.client("iam")
            paginator = iam.get_paginator("list_account_aliases")
            for aliases in paginator.paginate(PaginationConfig={"MaxItems": 1}):
                if "AccountAliases" in aliases and len(aliases["AccountAliases"]) > 0:
                    account_name = aliases["AccountAliases"][0]
                    break
        except Exception as e:
            logger.warning(f"Failed to get account alias: {str(e)}")

    if not account_name:
        try:
            sts_client = boto3.client("sts")
            account_id = retry_api_call(sts_client.get_caller_identity).get("Account")
            account_name = account_id if account_id else "[NOT FOUND]"
        except Exception as e:
            logger.warning(f"Failed to get account ID: {str(e)}")
            account_name = "[NOT FOUND]"
    
    logger.info(f"Using account name: {account_name}")

    client = boto3.client('ce')

    query = {
        "TimePeriod": {
            "Start": week_ago.strftime('%Y-%m-%d'),
            "End": today.strftime('%Y-%m-%d'),
        },
        "Granularity": "DAILY",
        "Filter": {
            "Not": {
                "Dimensions": {
                    "Key": "RECORD_TYPE",
                    "Values": [
                        "Credit",
                        "Refund",
                        "Upfront",
                        "Support",
                    ]
                }
            }
        },
        "Metrics": [cost_aggregation],
        "GroupBy": [
            {
                "Type": "DIMENSION",
                "Key": group_by,
            },
        ],
    }

    # Only run the query when on lambda, not when testing locally with example json
    if result is None:
        try:
            result = retry_api_call(client.get_cost_and_usage, **query)
        except ClientError as e:
            logger.error(f"AWS Cost Explorer API error: {str(e)}")
            raise Exception(f"Failed to retrieve cost data from AWS: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error calling Cost Explorer: {str(e)}")
            raise

    cost_per_day_by_service = defaultdict(list)

    if new_method == False:
        # Build a map of service -> array of daily costs for the time frame
        for day in result.get('ResultsByTime', []):
            for group in day.get('Groups', []):
                key = group['Keys'][0]
                cost = float(group['Metrics'][cost_aggregation]['Amount'])
                cost_per_day_by_service[key].append(cost)
    else:
        # New method, which first creates a dict of dicts
        # then loop over the services and loop over the list_of_dates
        # and this means even for sparse data we get a full list of costs
        cost_per_day_dict = defaultdict(dict)

        for day in result.get('ResultsByTime', []):
            start_date = day["TimePeriod"]["Start"]
            for group in day.get('Groups', []):
                key = group['Keys'][0]
                if group_by == "LINKED_ACCOUNT":
                    dimension = find_by_key(result.get("DimensionValueAttributes", []), "Value", key)
                    if dimension:
                        key += " ("+dimension["Attributes"]["description"]+")"
                cost = float(group['Metrics'][cost_aggregation]['Amount'])
                cost_per_day_dict[key][start_date] = cost

        for key in cost_per_day_dict.keys():
            for start_date in list_of_dates:
                cost = cost_per_day_dict[key].get(start_date, 0.0)  # fallback for sparse data
                cost_per_day_by_service[key].append(cost)

    # Sort the map by yesterday's cost
    most_expensive_yesterday = sorted(
        cost_per_day_by_service.items(), 
        key=lambda i: i[1][-1] if i[1] else 0, 
        reverse=True
    )

    service_names = [k for k,_ in most_expensive_yesterday[:length]]
    if not service_names:
        longest_name_len = 10
    else:
        longest_name_len = len(max(service_names, key=len))

    yesterday_date = yesterday.strftime('%Y-%m-%d')
    buffer = f"{'Service':<{longest_name_len}} ${'Cost':>8} {'∆%':>6} {'Trend':>7}\n"

    for service_name, costs in most_expensive_yesterday[:length]:
        if not costs:
            continue
        buffer += f"{service_name:<{longest_name_len}} ${costs[-1]:>8,.2f} {delta(costs):>5.0f}% {sparkline(costs):>7}\n"

    other_costs = [0.0] * n_days
    for service_name, costs in most_expensive_yesterday[length:]:
        for i, cost in enumerate(costs):
            if i < len(other_costs):
                other_costs[i] += cost

    if other_costs:
        buffer += f"{'Other':<{longest_name_len}} ${other_costs[-1]:>8,.2f} {delta(other_costs):>5.0f}% {sparkline(other_costs):>7}\n"

    total_costs = [0.0] * n_days
    for day_number in range(n_days):
        for service_name, costs in most_expensive_yesterday:
            try:
                if day_number < len(costs):
                    total_costs[day_number] += costs[day_number]
            except (IndexError, TypeError):
                total_costs[day_number] += 0.0

    buffer += f"{'Total':<{longest_name_len}} ${total_costs[-1]:>8,.2f} {delta(total_costs):>5.0f}% {sparkline(total_costs):>7}\n"

    cost_per_day_by_service["total"] = total_costs[-1]

    # Get detailed EC2 breakdown if EC2 - Other is in top services
    detailed_ec2_breakdown = {}
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    # Check if we need detailed EC2 breakdown (only if result was from API, not test data)
    if result is None:  # Only query if we're using real API (not test data)
        for service_name, costs in most_expensive_yesterday[:length]:
            if "EC2 - Other" in service_name and costs[-1] > EC2_COST_THRESHOLD:
                try:
                    detailed_ec2_breakdown = get_detailed_ec2_breakdown(client, yesterday_str)
                    logger.info(f"Retrieved detailed EC2 breakdown with {len(detailed_ec2_breakdown)} items")
                    break
                except Exception as e:
                    logger.warning(f"Could not get detailed EC2 breakdown: {str(e)}")

    # Generate cost reduction recommendations
    recommendations = get_cost_recommendations(most_expensive_yesterday, total_costs[-1], detailed_ec2_breakdown)

    credits_expire_date = os.environ.get('CREDITS_EXPIRE_DATE')
    if credits_expire_date:
        try:
            credits_expire_date = datetime.datetime.strptime(credits_expire_date, "%m/%d/%Y")

            credits_remaining_as_of = os.environ.get('CREDITS_REMAINING_AS_OF')
            if credits_remaining_as_of:
                credits_remaining_as_of = datetime.datetime.strptime(credits_remaining_as_of, "%m/%d/%Y")
            else:
                credits_remaining_as_of = today

            credits_remaining_str = os.environ.get('CREDITS_REMAINING', '0')
            credits_remaining = float(credits_remaining_str)

            days_left_on_credits = (credits_expire_date - credits_remaining_as_of).days
            if days_left_on_credits > 0:
                allowed_credits_per_day = credits_remaining / days_left_on_credits
            else:
                allowed_credits_per_day = credits_remaining

            relative_to_budget = (total_costs[-1] / allowed_credits_per_day) * 100.0 if allowed_credits_per_day > 0 else 0

            if relative_to_budget < 60:
                emoji = ":white_check_mark:"
            elif relative_to_budget > 110:
                emoji = ":rotating_light:"
            else:
                emoji = ":warning:"

            summary = (f"{emoji} Yesterday's cost for {account_name}: ${total_costs[-1]:,.2f} "
                       f"({relative_to_budget:.1f}% of daily credit budget ${allowed_credits_per_day:,.2f})")
        except Exception as e:
            logger.warning(f"Error processing credits information: {str(e)}")
            summary = f"📊 Yesterday's cost for account {account_name}: ${total_costs[-1]:,.2f}"
    else:
        summary = f"📊 Yesterday's cost for account {account_name}: ${total_costs[-1]:,.2f}"

    # Return the date for the report
    report_date = yesterday.strftime('%Y-%m-%d')
    return summary, buffer, cost_per_day_by_service, recommendations, detailed_ec2_breakdown, report_date


def publish_slack(
    hook_url: str, 
    summary: str, 
    buffer: str, 
    recommendations: List[str], 
    user_ids: Optional[List[str]] = None,
    total_cost: float = 0.0,
    mention_here: bool = False,
    report_date: str = None
):
    """Publish cost report to Slack with rich formatting."""
    if user_ids is None:
        user_ids = []

    # Format user mentions properly
    mentions = []
    if mention_here:
        mentions.append("<!here>")
    if user_ids:
        mentions.extend([f"<@{uid}>" for uid in user_ids])
    
    user_mentions = ' '.join(mentions) if mentions else ""
    
    # Use provided report date or calculate yesterday
    if report_date is None:
        report_date = (datetime.datetime.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Build Slack blocks for rich formatting
    blocks = []
    
    # Header block
    if user_mentions:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{user_mentions}\n\n*{summary}*"
            }
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{summary}*"
            }
        })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Cost breakdown block
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Daily Cost Breakdown ({report_date})*\n```\n{buffer}\n```"
        }
    })
    
    # Recommendations block
    if recommendations:
        blocks.append({"type": "divider"})
        recommendations_text = "\n".join(recommendations)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💡 Cost Optimization Recommendations*\n{recommendations_text}"
            }
        })
    
    # Footer with timestamp
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Generated at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            }
        ]
    })
    
    # Post the message to Slack
    payload = {
        "blocks": blocks,
        "text": summary  # Fallback text for notifications
    }
    
    try:
        resp = requests.post(
            hook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        resp.raise_for_status()
        logger.info(f"Successfully sent message to Slack. Status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to Slack: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}, body: {e.response.text}")
        raise


def publish_teams(hook_url: str, summary: str, buffer: str):
    """Publish cost report to Microsoft Teams."""
    try:
        payload = {
            "text": summary + "\n\n```\n" + buffer + "\n```",
        }
        resp = requests.post(hook_url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info(f"Successfully sent message to Teams. Status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to Teams: {str(e)}")
        raise


def publish_google(hook_url: str, summary: str, buffer: str):
    """Publish cost report to Google Chat."""
    try:
        message = {
            "text": summary + "\n\n```\n" + buffer + "\n```"
        }
        resp = requests.post(hook_url, json=message, timeout=30)
        resp.raise_for_status()
        logger.info(f"Successfully sent message to Google Chat. Status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message to Google Chat: {str(e)}")
        raise


if __name__ == "__main__":
    # for running locally to test
    import json
    with open("example_boto3_result.json", "r") as f:
        example_result = json.load(f)
    with open("example_boto3_result2.json", "r") as f:
        example_result2 = json.load(f)

    # New Method with 2 example jsons
    summary, buffer, cost_dict, recommendations, detailed_ec2, report_date = report_cost(
        None, None, "UnblendedCost", example_result, yesterday="2021-08-23", new_method=True
    )
    assert "{0:.2f}".format(cost_dict.get("total", 0.0)) == "286.37", f'{cost_dict.get("total"):,.2f} != 286.37'
    
    summary, buffer, cost_dict, recommendations, detailed_ec2, report_date = report_cost(
        None, None, "UnblendedCost", example_result2, yesterday="2021-08-29", new_method=True
    )
    assert "{0:.2f}".format(cost_dict.get("total", 0.0)) == "21.45", f'{cost_dict.get("total"):,.2f} != 21.45'
    
    print("All tests passed!")
    print(f"\nSummary: {summary}")
    print(f"\nBuffer:\n{buffer}")
    print(f"\nRecommendations:\n" + "\n".join(recommendations))
    print(f"\nReport Date: {report_date}")
