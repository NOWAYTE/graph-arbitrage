import boto3
import pandas as pd
import numpy as np
import json
import logging
from datetime import datetime
import io

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

RAW_BUCKET = 'graph-arbitrage-raw-data-se'
PROCESSED_BUCKET = 'graph-arbitrage-processed-data-se'


def calculate_currency_values(fx_rates_df):
    try:
        currencies = set()
        for pair in fx_rates_df['pair']:
            pair_clean = pair.replace('=X', '')
            if len(pair_clean) == 6:
                base = pair_clean[:3]
                quote = pair_clean[3:]
                currencies.add(base)
                currencies.add(quote)

        currencies = sorted(list(currencies))
        n_currencies = len(currencies)
        currency_to_idx = {curr: idx for idx, curr in enumerate(currencies)}

        logger.info(f"Processing {n_currencies} currencies: {currencies}")

        equations = []
        targets = []

        for _, row in fx_rates_df.iterrows():
            pair = row['pair']
            rate = row['rate']
            if rate > 0:
                pair_clean = pair.replace('=X', '')
                if len(pair_clean) == 6:
                    base = pair_clean[:3]
                    quote = pair_clean[3:]
                    if base in currency_to_idx and quote in currency_to_idx:
                        equation = [0] * n_currencies
                        equation[currency_to_idx[base]] = 1
                        equation[currency_to_idx[quote]] = -1
                        equations.append(equation)
                        targets.append(np.log(rate))

        if not equations:
            raise ValueError("No valid equations could be built from the data")

        equations.append([1] * n_currencies)
        targets.append(0)

        A = np.array(equations)
        b = np.array(targets)

        logV, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)

        currency_values = {currency: float(np.exp(logV[i])) for i, currency in enumerate(currencies)}

        logger.info(f"Calculated currency values: {currency_values}")
        return currency_values

    except Exception as e:
        logger.error(f"Error calculating currency values: {str(e)}")
        raise


def detect_arbitrage_opportunities(fx_rates_df, currency_values):
    opportunities = []
    try:
        for _, row in fx_rates_df.iterrows():
            pair = row['pair']
            market_rate = row['rate']
            pair_clean = pair.replace('=X', '')
            if len(pair_clean) == 6:
                base = pair_clean[:3]
                quote = pair_clean[3:]
                if base in currency_values and quote in currency_values:
                    theoretical_rate = currency_values[base] / currency_values[quote]
                    arb_percentage = (market_rate - theoretical_rate) / theoretical_rate * 100
                    if abs(arb_percentage) > 0.1:
                        opportunities.append({
                            'pair': pair,
                            'market_rate': float(market_rate),
                            'theoretical_rate': float(theoretical_rate),
                            'arbitrage_percentage': float(arb_percentage),
                            'base_currency_value': float(currency_values[base]),
                            'quote_currency_value': float(currency_values[quote])
                        })

        logger.info(f"Found {len(opportunities)} potential opportunities")
        return opportunities

    except Exception as e:
        logger.error(f"Error detecting arbitrage: {str(e)}")
        raise


def lambda_handler(event, context):
    logger.info("Data processing")
    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        logger.info(f"Processing file s3://{bucket}/{key}")

        response = s3_client.get_object(Bucket=bucket, Key=key)
        csv_content = response['Body'].read().decode('utf-8')

        fx_rates_df = pd.read_csv(io.StringIO(csv_content))
        # Normalize column names to lowercase
        fx_rates_df.columns = [c.strip().lower() for c in fx_rates_df.columns]

        logger.info(f"Loaded {len(fx_rates_df)} currency pairs")

        filename = key.split('/')[-1]
        date_str = filename.split('_')[0]

        currency_values = calculate_currency_values(fx_rates_df)
        arbitrage_ops = detect_arbitrage_opportunities(fx_rates_df, currency_values)

        processed_data = {
            'processing_timestamp': datetime.utcnow().isoformat(),
            'source_file': key,
            'date': date_str,
            'currency_values': currency_values,
            'arbitrage_opportunities': arbitrage_ops,
            'summary_stats': {
                'total_pairs': len(fx_rates_df),
                'currencies_covered': len(currency_values),
                'opportunities_found': len(arbitrage_ops),
                'average_rate': float(fx_rates_df['rate'].mean()),
                'rate_std_dev': float(fx_rates_df['rate'].std())
            },
            'raw_data_sample': fx_rates_df.head().to_dict('records')
        }

        processed_key = f"processed/{date_str}/analysis.json"
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=processed_key,
            Body=json.dumps(processed_data, indent=2),
            ContentType='application/json'
        )

        currency_df = pd.DataFrame([{'currency': curr, 'value': val} for curr, val in currency_values.items()])
        csv_output = currency_df.to_csv(index=False)
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=f"processed/{date_str}/currency_values.csv",
            Body=csv_output,
            ContentType='text/csv'
        )

        if arbitrage_ops:
            arb_df = pd.DataFrame(arbitrage_ops)
            arb_csv = arb_df.to_csv(index=False)
            s3_client.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=f"processed/{date_str}/arbitrage_opportunities.csv",
                Body=arb_csv,
                ContentType='text/csv'
            )

        logger.info(f"Successfully processed data for {date_str}")
        logger.info(f"Found {len(arbitrage_ops)} arbitrage opportunities")
        logger.info(f"Saved to: s3://{PROCESSED_BUCKET}/{processed_key}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data processing completed successfully',
                'date': date_str,
                'currencies_processed': len(currency_values),
                'arbitrage_opportunities': len(arbitrage_ops),
                'output_location': f"s3://{PROCESSED_BUCKET}/{processed_key}"
            })
        }

    except Exception as e:
        logger.error(f"Data processing failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Data processing failed: {str(e)}'})
        }

