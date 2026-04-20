import json
import boto3
import pickle
import os
from datetime import datetime

MODEL_BUCKET = os.environ.get("MODEL_BUCKET", "tu-bucket-aqui")
MODEL_KEY = "models/model.pkl"
LOG_BUCKET = os.environ.get("LOG_BUCKET", "tu-bucket-aqui")

model = None


def load_model():
    global model
    if model is None:
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=MODEL_BUCKET, Key=MODEL_KEY)
        model = pickle.loads(response["Body"].read())
    return model


def prepare_features(hour, temperature, humidity, is_weekend, is_holiday):
    return [[hour, temperature, humidity, is_weekend, is_holiday]]


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))

        hour = int(body.get("hour", datetime.now().hour))
        temperature = float(body.get("temperature", 20))
        humidity = float(body.get("humidity", 50))
        is_weekend = int(body.get("is_weekend", 0))
        is_holiday = int(body.get("is_holiday", 0))

        m = load_model()
        features = prepare_features(hour, temperature, humidity, is_weekend, is_holiday)
        prediction = m.predict(features)[0]

        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "input": {
                "hour": hour,
                "temperature": temperature,
                "humidity": humidity,
                "is_weekend": is_weekend,
                "is_holiday": is_holiday,
            },
            "prediction": float(prediction),
            "model_version": "1.0.0",
        }

        now = datetime.utcnow()
        s3_key = f"predictions/{now.year}/{now.month:02d}/{now.day:02d}/{now.strftime('%H-%M')}-prediction.json"

        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=LOG_BUCKET,
            Key=s3_key,
            Body=json.dumps(log_entry),
            ContentType="application/json",
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "available_bikes": int(prediction),
                    "timestamp": log_entry["timestamp"],
                }
            ),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
