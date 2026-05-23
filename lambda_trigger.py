"""
lambda_trigger.py
-----------------
AWS Lambda function to trigger the BuyCrash API on a schedule.
Deploy this to Lambda and attach an EventBridge rule to it.

Setup:
  1. Create a Lambda function (Python 3.11, ~128MB, 10s timeout)
  2. Paste this code into the Lambda editor
  3. Set environment variables in Lambda:
       API_URL  = http://<your-ec2-ip>:5000
       API_KEY  = your_secret_key_here
  4. Create an EventBridge rule:
       Schedule: cron(0 8 * * ? *)  ← runs daily at 8am UTC
       Target: this Lambda function
  5. Make sure your EC2 Security Group allows inbound TCP on port 5000
     from the Lambda's IP (or 0.0.0.0/0 if behind auth)
"""
import os
import json
import urllib.request
import urllib.error


def lambda_handler(event, context):
    api_url = os.environ.get("API_URL", "").rstrip("/")
    api_key = os.environ.get("API_KEY", "")

    if not api_url:
        return {"statusCode": 500, "body": "API_URL not set"}

    url     = f"{api_url}/start"
    payload = json.dumps({}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data    = payload,
        method  = "POST",
        headers = {
            "Content-Type": "application/json",
            "X-API-Key":    api_key,
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            print(f"Response {resp.status}: {body}")
            return {"statusCode": resp.status, "body": body}

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"HTTP Error {e.code}: {body}")
        # 400 "already running" is fine — not a real error
        if e.code == 400 and "already running" in body:
            return {"statusCode": 200, "body": "Already running — OK"}
        return {"statusCode": e.code, "body": body}

    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": str(e)}