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

def process_historical_data(historical_data):
    """Process multiple days of historical data for GNN training"""
    processed_days = []
    
    # Get all unique dates from the first currency pair
    first_pair = list(historical_data['fx_rates'].keys())[0]
    all_dates = historical_data['fx_rates'][first_pair]['dates']
    
    logger.info(f"Processing {len(all_dates)} days of historical data")
    
    # Process each day
    for day_index, date in enumerate(all_dates):
        daily_rates = []
        
        # Collect rates for all pairs for this specific day
        for pair, pair_data in historical_data['fx_rates'].items():
            if day_index < len(pair_data['closes']):
                daily_rates.append({
                    'pair': pair,
                    'rate': pair_data['closes'][day_index],
                    'date': date
                })
        
        # Only process days where we have sufficient data
        if len(daily_rates) >= 10:  # At least 10 pairs
            try:
                df = pd.DataFrame(daily_rates)
                currency_values = calculate_currency_values(df)
                arbitrage_ops = detect_arbitrage_opportunities(df, currency_values)
                
                processed_day = {
                    'date': date,
                    'currency_values': currency_values,
                    'arbitrage_opportunities': arbitrage_ops,
                    'summary_stats': {
                        'total_pairs': len(daily_rates),
                        'currencies_covered': len(currency_values),
                        'opportunities_found': len(arbitrage_ops),
                        'average_rate': float(df['rate'].mean()),
                        'rate_std_dev': float(df['rate'].std())
                    },
                    'raw_data_sample': df.head().to_dict('records')
                }
                processed_days.append(processed_day)
                
                logger.info(f"Processed day {date}: {len(arbitrage_ops)} opportunities")
                
            except Exception as e:
                logger.error(f"Error processing day {date}: {str(e)}")
                continue
        else:
            logger.warning(f"Skipping day {date}: insufficient data ({len(daily_rates)} pairs)")
    
    return processed_days

def lambda_handler(event, context):
    logger.info("Data processing started")
    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        logger.info(f"Processing file s3://{bucket}/{key}")

        # Check if it's the new JSON format or old CSV format
        if key.endswith('.json'):
            # NEW: Process historical JSON data
            response = s3_client.get_object(Bucket=bucket, Key=key)
            json_content = response['Body'].read().decode('utf-8')
            historical_data = json.loads(json_content)
            
            # Validate the new data structure
            if 'fx_rates' not in historical_data or 'interest_rates' not in historical_data:
                raise ValueError("Invalid JSON structure: missing fx_rates or interest_rates")
            
            # Process all historical days
            processed_days = process_historical_data(historical_data)
            
            # Prepare output
            filename = key.split('/')[-1]
            date_str = filename.replace('fx_historical_', '').replace('.json', '')
            
            processed_data = {
                'processing_timestamp': datetime.utcnow().isoformat(),
                'source_file': key,
                'date_range': historical_data.get('date_range', {}),
                'interest_rates': historical_data.get('interest_rates', {}),
                'fetch_timestamp': historical_data.get('fetch_timestamp', ''),
                'data_sources': historical_data.get('data_sources', {}),
                'processed_days': processed_days,
                'summary': {
                    'total_days_processed': len(processed_days),
                    'total_opportunities_found': sum(len(day['arbitrage_opportunities']) for day in processed_days),
                    'currencies_tracked': list(processed_days[0]['currency_values'].keys()) if processed_days else [],
                    'date_range_processed': {
                        'start': processed_days[0]['date'] if processed_days else None,
                        'end': processed_days[-1]['date'] if processed_days else None
                    }
                }
            }
            
            # Save to S3
            processed_key = f"processed/historical/{date_str}/analysis.json"
            s3_client.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=processed_key,
                Body=json.dumps(processed_data, indent=2),
                ContentType='application/json'
            )
            
            # Also save individual day data for easier GNN training
            for day in processed_days:
                day_key = f"processed/daily/{day['date']}/analysis.json"
                s3_client.put_object(
                    Bucket=PROCESSED_BUCKET,
                    Key=day_key,
                    Body=json.dumps(day, indent=2),
                    ContentType='application/json'
                )
            
            logger.info(f"Successfully processed {len(processed_days)} days of historical data")
            logger.info(f"Found {processed_data['summary']['total_opportunities_found']} total opportunities")
            logger.info(f"Interest rates: {historical_data.get('interest_rates', {})}")
            
        else:
            # OLD: Process single day CSV data (backward compatibility)
            response = s3_client.get_object(Bucket=bucket, Key=key)
            csv_content = response['Body'].read().decode('utf-8')
            fx_rates_df = pd.read_csv(io.StringIO(csv_content))
            fx_rates_df.columns = [c.strip().lower() for c in fx_rates_df.columns]

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

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data processing completed successfully',
                'output_location': f"s3://{PROCESSED_BUCKET}/{processed_key}",
                'days_processed': len(processed_days) if key.endswith('.json') else 1,
                'total_opportunities': processed_data['summary']['total_opportunities_found'] if key.endswith('.json') else len(arbitrage_ops)
            })
        }

    except Exception as e:
        logger.error(f"Data processing failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Data processing failed: {str(e)}'})
        }
