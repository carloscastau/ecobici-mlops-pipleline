import json
import boto3
import requests
import os
from datetime import datetime

API_URL = "https://gbfs.mex.lyftbikes.com/gbfs/en/station_status.json"
BUCKET_NAME = os.environ.get("BUCKET_NAME", "tu-bucket-aqui")


def lambda_handler(event, context):
    return main()


def main():
    print("Ingesting EcoBici data...")

    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()
    data = response.json()

    last_updated = data.get("last_updated")
    stations = data.get("data", {}).get("stations", [])

    # Transformar cada estación: añadir last_updated y mantener solo campos de Athena
    processed_stations = []
    for station in stations:
        processed_stations.append(
            {
                "station_id": station.get("station_id"),
                "num_bikes_available": station.get("num_bikes_available"),
                "num_docks_available": station.get("num_docks_available"),
                "last_reported": station.get("last_reported"),
                "last_updated": last_updated,
            }
        )

    # Convertir a JSON Lines
    json_lines = "\n".join(json.dumps(s) for s in processed_stations)

    now = datetime.utcnow()
    s3_key = f"raw/{now.year}/{now.month:02d}/{now.day:02d}/{now.strftime('%H-%M')}-status.jsonl"

    s3_client = boto3.client("s3")
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=s3_key,
        Body=json_lines,
        ContentType="application/json",
    )

    print(f"Uploaded to s3://{BUCKET_NAME}/{s3_key}")
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Success", "key": s3_key}),
    }


if __name__ == "__main__":
    main()
