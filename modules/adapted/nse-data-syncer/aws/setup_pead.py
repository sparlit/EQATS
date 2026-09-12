import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


#!/usr/bin/env python3
"""
One-time AWS setup for the PEAD system.
Run this locally with AWS credentials configured.

Prerequisites:
    pip install boto3
    aws configure   # or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars

Usage:
    python aws/setup_pead.py
"""

import contextlib
import io
import json
import os
import sys
import time
import zipfile

import boto3

REGION = os.environ.get("AWS_REGION", "ap-south-1")
ACCOUNT_ID = None  # filled in at runtime

ROLE_NAME = "pead-lambda-role"
POLLER_NAME = "pead-poller"
PROCESSOR_NAME = "pead-processor"
QUEUE_NAME = "pead-results-queue"
RULE_NAME = "pead-poller-schedule"

TRUST_POLICY = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)

SQS_POLICY = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
                "Resource": "*",
            }
        ],
    }
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def make_zip(handler_filename: str) -> bytes:
    """Create a zip containing just the handler file (no dependencies)."""
    buf = io.BytesIO()
    src = os.path.join(SCRIPT_DIR, "pead", handler_filename)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, arcname=handler_filename)
    return buf.getvalue()


def p(msg):
    print(f"  {msg}")


def setup():
    iam = boto3.client("iam", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)
    sqs = boto3.client("sqs", region_name=REGION)
    events = boto3.client("events", region_name=REGION)
    sts = boto3.client("sts", region_name=REGION)

    global ACCOUNT_ID
    ACCOUNT_ID = sts.get_caller_identity()["Account"]
    print(f"\nAWS Account: {ACCOUNT_ID}  Region: {REGION}")

    # ── 1. IAM Role ───────────────────────────────────────────────────────────
    print("\n[1/5] IAM Role")
    try:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=TRUST_POLICY,
            Description="Execution role for PEAD Lambda functions",
        )
        role_arn = role["Role"]["Arn"]
        p(f"Created role: {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        p(f"Role already exists: {role_arn}")

    for policy_arn in [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonSQSFullAccess",
    ]:
        try:
            iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=policy_arn)
            p(f"Attached: {policy_arn.split('/')[-1]}")
        except Exception:
            p(f"Already attached: {policy_arn.split('/')[-1]}")

    p("Waiting 10s for IAM to propagate...")
    time.sleep(10)

    # ── 2. SQS Queue (standard, 15-min delay) ────────────────────────────────
    print("\n[2/5] SQS Queue")
    try:
        q = sqs.create_queue(
            QueueName=QUEUE_NAME,
            Attributes={
                "DelaySeconds": "900",  # 15 min default delay
                "VisibilityTimeout": "360",  # 6 min (matches processor timeout)
                "MessageRetentionPeriod": "86400",
            },
        )
        queue_url = q["QueueUrl"]
        p(f"Created queue: {queue_url}")
    except sqs.exceptions.QueueAlreadyExists:
        queue_url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
        p(f"Queue already exists: {queue_url}")

    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]

    # ── 3. Lambda: pead-poller ────────────────────────────────────────────────
    poller_zip = make_zip("poller.py")
    processor_zip = make_zip("processor.py")

    print("\n[3/5] Lambda: pead-poller")
    poller_env = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", "REPLACE_ME"),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", "REPLACE_ME"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", "REPLACE_ME"),
        "SQS_QUEUE_URL": queue_url,
    }
    try:
        fn = lam.create_function(
            FunctionName=POLLER_NAME,
            Runtime="python3.11",
            Role=role_arn,
            Handler="poller.lambda_handler",
            Code={"ZipFile": poller_zip},
            Timeout=60,
            MemorySize=256,
            Environment={"Variables": poller_env},
            Description="PEAD: poll NSE announcements every minute",
        )
        p(f"Created: {fn['FunctionArn']}")
    except lam.exceptions.ResourceConflictException:
        lam.update_function_configuration(
            FunctionName=POLLER_NAME,
            Environment={"Variables": poller_env},
        )
        p("Already exists — environment vars updated")

    poller_arn = lam.get_function(FunctionName=POLLER_NAME)["Configuration"]["FunctionArn"]

    # ── 4. Lambda: pead-processor ─────────────────────────────────────────────
    print("\n[4/5] Lambda: pead-processor")
    processor_env = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", "REPLACE_ME"),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", "REPLACE_ME"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", "REPLACE_ME"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "REPLACE_ME"),
        "SCREENER_USERNAME": os.environ.get("SCREENER_USERNAME", "REPLACE_ME"),
        "SCREENER_PASSWORD": os.environ.get("SCREENER_PASSWORD", "REPLACE_ME"),
    }
    try:
        fn = lam.create_function(
            FunctionName=PROCESSOR_NAME,
            Runtime="python3.11",
            Role=role_arn,
            Handler="processor.lambda_handler",
            Code={"ZipFile": processor_zip},
            Timeout=300,
            MemorySize=512,
            Environment={"Variables": processor_env},
            Description="PEAD: analyze results, call Claude, send Telegram signal",
        )
        p(f"Created: {fn['FunctionArn']}")
    except lam.exceptions.ResourceConflictException:
        lam.update_function_configuration(
            FunctionName=PROCESSOR_NAME,
            Environment={"Variables": processor_env},
        )
        p("Already exists — environment vars updated")

    processor_arn = lam.get_function(FunctionName=PROCESSOR_NAME)["Configuration"]["FunctionArn"]

    # Wire SQS → processor Lambda trigger
    try:
        lam.create_event_source_mapping(
            EventSourceArn=queue_arn,
            FunctionName=PROCESSOR_NAME,
            BatchSize=1,
            Enabled=True,
        )
        p("SQS trigger wired to processor")
    except lam.exceptions.ResourceConflictException:
        p("SQS trigger already exists")

    # ── 5. EventBridge rule (every 1 min, Mon–Fri, 8AM–9PM IST) ─────────────
    print("\n[5/5] EventBridge rule")
    # 8 AM–9 PM IST = 2:30 AM–3:30 PM UTC → use hours 3–15 UTC on weekdays
    try:
        events.put_rule(
            Name=RULE_NAME,
            ScheduleExpression="cron(* 3-15 ? * MON-FRI *)",
            State="ENABLED",
            Description="Trigger PEAD poller every minute during IST market hours",
        )
        p("Rule created/updated")

        rule_arn = events.describe_rule(Name=RULE_NAME)["Arn"]

        # Allow EventBridge to invoke the poller Lambda
        with contextlib.suppress(lam.exceptions.ResourceConflictException):
            lam.add_permission(
                FunctionName=POLLER_NAME,
                StatementId="pead-eventbridge-invoke",
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )

        events.put_targets(
            Rule=RULE_NAME,
            Targets=[{"Id": "pead-poller", "Arn": poller_arn}],
        )
        p(f"Target set → {POLLER_NAME}")
    except Exception as e:
        p(f"EventBridge error: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ AWS setup complete!\n")
    print("Next steps:")
    print("1. Add these GitHub Secrets (Settings → Secrets → Actions):")
    print("     AWS_ACCESS_KEY_ID")
    print("     AWS_SECRET_ACCESS_KEY")
    print("     PEAD_DATABASE_URL")
    print("     PEAD_TELEGRAM_BOT_TOKEN")
    print("     PEAD_TELEGRAM_CHAT_ID")
    print("     PEAD_ANTHROPIC_API_KEY")
    print("     PEAD_SCREENER_USERNAME")
    print("     PEAD_SCREENER_PASSWORD")
    print()
    print("2. Push code → GitHub Action will deploy both Lambdas")
    print()
    print(f"   SQS Queue URL : {queue_url}")
    print(f"   Poller ARN    : {poller_arn}")
    print(f"   Processor ARN : {processor_arn}")
    print("=" * 60)


if __name__ == "__main__":
    setup()
