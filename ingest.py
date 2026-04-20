import json
import boto3
import requests
import os
from datetime import datetime


def lambda_handler(event, context):
    API_URL = "https://gbfs.mex.lyftbikes.com/gbfs/en/station_status.json"
    BUCKET_NAME = os.environ.get("BUCKET_NAME", "tu-bucket-aqui")

    try:
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()

        timestamp = datetime.utcnow().isoformat()
        payload = {"timestamp": timestamp, "data": data}

        now = datetime.utcnow()
        s3_key = f"raw/{now.year}/{now.month:02d}/{now.day:02d}/{now.strftime('%H-%M')}-status.json"

        s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Data uploaded", "key": s3_key}),
        }

    except requests.exceptions.RequestException as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
