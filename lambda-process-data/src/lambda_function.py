import boto3
import pandas as pd
import numpy as np
import json
import logging
from datetime import datetime
import itertools
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


def validate_fx_data(fx_rates_df):
    currencies = set()
    for pair in fx_rates_df['pair']:
        pair_clean = pair.replace('=X', '')
        if len(pair_clean) == 6:
            currencies.add(pair_clean[:3])
            currencies.add(pair_clean[3:])

    expected_pairs = len(currencies) * (len(currencies) - 1) / 2
    actual_pairs = len(fx_rates_df)
    integrity = "PASS" if actual_pairs >= expected_pairs * 0.9 else "FAIL"

    return {
        "currencies": sorted(list(currencies)),
        "expected_pairs": int(expected_pairs),
        "actual_pairs": int(actual_pairs),
        "status": integrity
    }


def detect_triangular_arbitrage(fx_rates_df):
    rates = {}
    for _, row in fx_rates_df.iterrows():
        pair_clean = row['pair'].replace('=X', '')
        if len(pair_clean) == 6:
            base, quote = pair_clean[:3], pair_clean[3:]
            rates[(base, quote)] = row['rate']

    opportunities = []
    currencies = list({c for a, b in rates.keys() for c in [a, b]})

    for a, b, c in itertools.permutations(currencies, 3):
        if (a, b) in rates and (b, c) in rates and (c, a) in rates:
            product = rates[(a, b)] * rates[(b, c)] * rates[(c, a)]
            if product > 1.001:
                profit_pct = (product - 1) * 100
                opportunities.append({
                    "cycle": f"{a}->{b}->{c}->{a}",
                    "profit_pct": round(profit_pct, 4),
                    "links": [
                        {"pair": f"{a}{b}=X", "rate": rates[(a, b)]},
                        {"pair": f"{b}{c}=X", "rate": rates[(b, c)]},
                        {"pair": f"{c}{a}=X", "rate": rates[(c, a)]},
                    ]
                })

    return opportunities


def detect_interest_rate_arbitrage(fx_rates_df, interest_rates):
    opportunities = []

    for _, row in fx_rates_df.iterrows():
        pair_clean = row['pair'].replace('=X', '')
        if len(pair_clean) == 6:
            base, quote = pair_clean[:3], pair_clean[3:]

            if base in interest_rates and quote in interest_rates:
                try:
                    base_rate = interest_rates[base]
                    quote_rate = interest_rates[quote]
                    spot_rate = row['rate']
                    expected_rate = spot_rate * (1 + base_rate) / (1 + quote_rate)
                    deviation_pct = (spot_rate - expected_rate) / expected_rate * 100

                    if abs(deviation_pct) > 0.1:
                        opportunities.append({
                            "pair": f"{base}{quote}=X",
                            "spot_rate": round(spot_rate, 6),
                            "expected_rate": round(expected_rate, 6),
                            "base_rate": base_rate,
                            "quote_rate": quote_rate,
                            "deviation_pct": round(deviation_pct, 4)
                        })
                except Exception as e:
                    logger.warning(f"Error computing interest-rate arbitrage for {pair_clean}: {str(e)}")
                    continue

    logger.info(f"Found {len(opportunities)} interest-rate arbitrage opportunities.")
    return opportunities


def generate_summary_report(processed_days, data_validation):
    if not processed_days:
        return {"error": "No data processed"}

    total_days = len(processed_days)
    total_opps = sum(len(day['arbitrage_opportunities']) for day in processed_days)
    avg_rate_std = np.mean([day['summary_stats']['rate_std_dev'] for day in processed_days])
    interest_opps = sum(
        1 for day in processed_days for op in day['arbitrage_opportunities']
        if 'deviation_pct' in op
    )

    return {
        "summary_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "days_processed": total_days,
        "average_rate_stddev": round(avg_rate_std, 5),
        "arbitrage_opportunities_found": total_opps,
        "interest_rate_arbitrage_found": interest_opps,
        "data_integrity": data_validation['status'],
        "currencies_tracked": data_validation['currencies'],
        "expected_pairs": data_validation['expected_pairs'],
        "actual_pairs": data_validation['actual_pairs']
    }


def process_historical_data(historical_data):
    processed_days = []
    first_pair = list(historical_data['fx_rates'].keys())[0]
    all_dates = historical_data['fx_rates'][first_pair]['dates']

    logger.info(f"Processing {len(all_dates)} days of historical data")

    for day_index, date in enumerate(all_dates):
        daily_rates = []

        for pair, pair_data in historical_data['fx_rates'].items():
            if day_index < len(pair_data['closes']):
                daily_rates.append({
                    'pair': pair,
                    'rate': pair_data['closes'][day_index],
                    'date': date
                })

        if len(daily_rates) >= 10:
            try:
                df = pd.DataFrame(daily_rates)
                currency_values = calculate_currency_values(df)
                arbitrage_ops = detect_arbitrage_opportunities(df, currency_values)
                validation = validate_fx_data(df)
                triangular_ops = detect_triangular_arbitrage(df)
                arbitrage_ops.extend(triangular_ops)

                if 'interest_rates' in historical_data:
                    interest_ops = detect_interest_rate_arbitrage(df, historical_data['interest_rates'])
                    arbitrage_ops.extend(interest_ops)

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

        if key.endswith('.json'):
            response = s3_client.get_object(Bucket=bucket, Key=key)
            json_content = response['Body'].read().decode('utf-8')
            historical_data = json.loads(json_content)

            if 'fx_rates' not in historical_data or 'interest_rates' not in historical_data:
                raise ValueError("Invalid JSON structure: missing fx_rates or interest_rates")

            processed_days = process_historical_data(historical_data)
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

            # Save historical analysis
            processed_key = f"processed/historical/{date_str}/analysis.json"
            s3_client.put_object(
                Bucket=PROCESSED_BUCKET,
                Key=processed_key,
                Body=json.dumps(processed_data, indent=2),
                ContentType='application/json'
            )

            # 🆕 NEW: Save last processed day into daily folder
            if processed_days:
                last_day = processed_days[-1]
                daily_key = f"processed/daily/{last_day['date']}/analysis.json"
                s3_client.put_object(
                    Bucket=PROCESSED_BUCKET,
                    Key=daily_key,
                    Body=json.dumps(last_day, indent=2),
                    ContentType="application/json"
                )
                logger.info(f"Daily snapshot saved to s3://{PROCESSED_BUCKET}/{daily_key}")

            # Generate summary report
            try:
                if processed_days:
                    last_day_df = pd.DataFrame(processed_days[-1]['raw_data_sample'])
                    validation = validate_fx_data(last_day_df)
                    report = generate_summary_report(processed_days, validation)
                    report_key = f"reports/{date_str}/report.json"
                    s3_client.put_object(
                        Bucket=PROCESSED_BUCKET,
                        Key=report_key,
                        Body=json.dumps(report, indent=2),
                        ContentType="application/json"
                    )
                    logger.info(f"Summary report saved to s3://{PROCESSED_BUCKET}/{report_key}")
            except Exception as e:
                logger.error(f"Report generation failed: {str(e)}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data processing completed successfully',
                'output_location': f"s3://{PROCESSED_BUCKET}/{processed_key}",
                'days_processed': len(processed_days),
                'total_opportunities': processed_data['summary']['total_opportunities_found']
            })
        }

    except Exception as e:
        logger.error(f"Data processing failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Data processing failed: {str(e)}'})
        }

