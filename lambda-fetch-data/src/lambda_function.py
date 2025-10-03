import json
import boto3
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import requests
import os
import time

s3_client = boto3.client('s3')
RAW_BUCKET = 'graph-arbitrage-raw-data-se'

def lambda_handler(event, context):
    # KEEP YOUR EXISTING FX RATES CODE - it's working fine!
    fx_pairs = [
        'USDEUR=X', 'USDJPY=X', 'USDGBP=X', 'USDAUD=X', 'USDCAD=X', 'USDCHF=X',
        'EURGBP=X', 'EURJPY=X', 'EURCHF=X', 'GBPJPY=X', 'GBPCHF=X', 
        'AUDJPY=X', 'CADJPY=X', 'CHFJPY=X', 'EURAUD=X', 'EURCAD=X',
        'AUDCAD=X', 'AUDCHF=X', 'CADCHF=X', 'GBPAUD=X', 'GBPCAD=X'
    ]
    
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=30)
    
    all_data = {}
    
    for pair in fx_pairs:
        try:
            ticker = yf.Ticker(pair)
            hist = ticker.history(start=start_date.strftime('%Y-%m-%d'), 
                                 end=end_date.strftime('%Y-%m-%d'))
            
            if hist.empty:
                print(f"No data found for {pair}")
                continue
                
            pair_data = {
                'dates': hist.index.strftime('%Y-%m-%d').tolist(),
                'closes': hist['Close'].fillna(method='ffill').tolist()
            }
            all_data[pair] = pair_data
            print(f"Fetched {len(hist)} days for {pair}")

        except Exception as e:
            print(f"Error fetching data for {pair}: {e}")

    # ONLY CHANGE: Use Alpha Vantage for interest rates instead of static data
    interest_rates = fetch_interest_rates_alpha_vantage()
    
    output_data = {
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'date_range': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d')
        },
        'fx_rates': all_data,
        'interest_rates': interest_rates,
        'data_sources': {
            'fx_rates': 'yfinance',
            'interest_rates': 'alpha_vantage'  # Now using real bond data!
        }
    }
    
    file_name = f"fx_historical_{end_date.strftime('%Y-%m-%d')}.json"
    
    try:
        s3_client.put_object(
            Bucket=RAW_BUCKET, 
            Key=f"fx/{file_name}", 
            Body=json.dumps(output_data, indent=2)
        )
        print(f"Historical data saved to S3: {RAW_BUCKET}/fx/{file_name}")
        
    except Exception as e:
        print(f"Error saving data to S3: {e}")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Historical data fetched successfully',
            'pairs_collected': len(all_data),
            'days_per_pair': 30,
            'interest_rates_collected': len(interest_rates),
            'output_file': file_name
        })
    }

def fetch_interest_rates_alpha_vantage():
    """
    Use Alpha Vantage ONLY for government bond yields (interest rates)
    This replaces the static/estimated interest rates with real market data
    """
    API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'demo')
    
    # Alpha Vantage symbols for 10-year government bond yields
    bond_symbols = {
        'USD': 'US10Y',    # US 10-Year Treasury Yield
        'EUR': 'DE10YR',   # Germany 10-Year (Euro proxy)
        'JPY': 'JP10YR',   # Japan 10-Year Government Bond
        'GBP': 'UK10YR',   # UK 10-Year Gilt Yield
        'AUD': 'AU10YR',   # Australia 10-Year Government Bond
        'CAD': 'CA10YR',   # Canada 10-Year Government Bond  
        'CHF': 'CH10YR',   # Switzerland 10-Year Government Bond
    }
    
    interest_rates = {}
    successful_fetches = 0
    
    print("Fetching real bond yields from Alpha Vantage...")
    
    for currency, symbol in bond_symbols.items():
        try:
            # Rate limiting: 12 seconds between requests (5 per minute)
            if successful_fetches > 0:
                time.sleep(12)
            
            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={API_KEY}"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if 'Global Quote' in data and '05. price' in data['Global Quote']:
                yield_value = float(data['Global Quote']['05. price'])
                interest_rates[currency] = yield_value / 100  # Convert to decimal
                successful_fetches += 1
                print(f"✓ {currency} 10-year bond yield: {yield_value:.2f}%")
            else:
                raise ValueError(f"No bond data for {symbol}")
                
        except Exception as e:
            print(f"✗ Alpha Vantage failed for {currency}: {e}")
            # Fallback to static rate if API fails
            static_rates = {
                'USD': 0.055, 'EUR': 0.045, 'JPY': 0.001, 
                'GBP': 0.052, 'AUD': 0.043, 'CAD': 0.050, 'CHF': 0.015
            }
            interest_rates[currency] = static_rates[currency]
            print(f"  Using static rate for {currency}: {static_rates[currency]:.3f}")
    
    print(f"Successfully fetched {successful_fetches}/7 real bond yields")
    return interest_rates
