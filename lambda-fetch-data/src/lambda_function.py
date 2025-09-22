import boto3
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

s3_client = boto3.client('s3')
RAW_BUCKET = 'graph-arbitrage-raw-data-se'
PROCESSED_BUCKET = 'graph-arbitrage-processed-data-se'

DYNAMODB_TABLE = 'fx-signals'

def lambda_handler(event, context):
    fx_pairs = ['USDEUR=X', 'USDJPY=X', 'USDGBP=X', 'USDAUD=X', 'USDCAD=X', 'USDCHF=X']

    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    data = {}

    for pair in fx_pairs:
        try:
            ticker = yf.Ticker(pair)
            hist = ticker.history(period='2d')
            yesterday_close = hist['Close'].iloc[-2]
            data[pair] = yesterday_close

        except Exception as e:
            print(f"Error fetching data for {pair}: {e}")

    df = pd.DataFrame(list(data.items()), columns=['Pair', 'Rate'])
    csv_string = df.to_csv(index=False)

    file_name = f"{yesterday}_forex_rates.csv"

    try:
        s3_client.put_object(Bucket=RAW_BUCKET, Key=f"fx/{file_name}", Body=csv_string)
        print(f"Data saved to S3 bucket: {RAW_BUCKET}/{file_name}")
    except Exception as e:
        print(f"Error saving data to S3: {e}")


    return {
        'statusCode': 200,
        'body': json.dumps(f'Data fetched successfully for {yesterday}')
    }
            