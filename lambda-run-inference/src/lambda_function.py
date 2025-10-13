import boto3
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add container paths
sys.path.append('/app')
sys.path.append('/app/inference')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Buckets and tables
PROCESSED_BUCKET = 'graph-arbitrage-processed-data-se'
MODELS_BUCKET = 'graph-arbitrage-models'
SIGNALS_TABLE = 'fx-signals'

# Your actual model path
MODEL_PATH = "v2/arbitrage_gnn_v2.pt"

def load_trained_model():
    """
    Load the trained GNN model from S3
    """
    try:
        import torch
        
        local_path = f'/tmp/{os.path.basename(MODEL_PATH)}'
        
        # Download from S3 if not exists locally
        if not os.path.exists(local_path):
            logger.info(f"Downloading model from S3: {MODEL_PATH}")
            s3_client.download_file(MODELS_BUCKET, MODEL_PATH, local_path)
            logger.info(f"Model downloaded successfully: {local_path}")
        
        # Load the model
        model = torch.load(local_path, map_location=torch.device('cpu'))
        model.eval()
        
        logger.info(f"Model loaded successfully: {type(model)}")
        logger.info(f"Model parameters: {sum(p.numel() for p in model.parameters())}")
        
        return model
        
    except Exception as e:
        logger.error(f"Error loading model {MODEL_PATH}: {str(e)}")
        raise

def prepare_inference_data(processed_data):
    """
    Prepare data for GNN inference
    This needs to match how your model was trained!
    """
    try:
        currency_values = processed_data['currency_values']
        currencies = sorted(list(currency_values.keys()))  # Important: consistent order
        
        logger.info(f"Preparing data for currencies: {currencies}")
        
        # Create node features - adjust based on your model's training
        node_features = []
        for currency in currencies:
            # Basic features - expand based on what your model expects
            features = [
                currency_values[currency],  # Currency value
                # Add more features here based on your training data
            ]
            
            # Add temporal features if available
            temporal_data = processed_data.get('temporal_features', {})
            if currency in temporal_data:
                features.extend(temporal_data[currency])
            
            node_features.append(features)
        
        # Create edge index (all possible currency pairs)
        edge_index = []
        edge_attributes = []
        
        for i in range(len(currencies)):
            for j in range(len(currencies)):
                if i != j:
                    edge_index.append([i, j])
                    # Calculate FX rate for this edge
                    rate = currency_values[currencies[i]] / currency_values[currencies[j]]
                    edge_attributes.append([rate])
        
        # Convert to tensors
        import torch
        node_tensor = torch.tensor(node_features, dtype=torch.float32)
        edge_tensor = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        edge_attr_tensor = torch.tensor(edge_attributes, dtype=torch.float32)
        
        inference_data = {
            'x': node_tensor,
            'edge_index': edge_tensor,
            'edge_attr': edge_attr_tensor,
            'currencies': currencies
        }
        
        logger.info(f"Prepared data: {len(currencies)} currencies, {len(edge_index)} edges")
        logger.info(f"Node features shape: {node_tensor.shape}")
        logger.info(f"Edge attributes shape: {edge_attr_tensor.shape}")
        
        return inference_data
        
    except Exception as e:
        logger.error(f"Error preparing inference data: {str(e)}")
        raise

def run_gnn_inference(model, inference_data):
    """
    Run GNN inference
    """
    try:
        import torch
        
        # Prepare the data in the format your model expects
        # This depends on your model's forward method signature
        if hasattr(model, 'forward'):
            with torch.no_grad():
                # Try different calling conventions
                try:
                    # If model expects Data object
                    from torch_geometric.data import Data
                    data = Data(
                        x=inference_data['x'],
                        edge_index=inference_data['edge_index'],
                        edge_attr=inference_data['edge_attr']
                    )
                    predictions = model(data)
                except:
                    # If model expects separate tensors
                    try:
                        predictions = model(
                            inference_data['x'],
                            inference_data['edge_index'],
                            inference_data['edge_attr']
                        )
                    except:
                        # Fallback: just pass the data dict
                        predictions = model(inference_data)
        else:
            # If it's a different type of model
            predictions = model.predict(inference_data)
        
        # Convert predictions to numpy for easier handling
        if isinstance(predictions, torch.Tensor):
            predictions = predictions.numpy()
        
        logger.info(f"Inference completed. Predictions type: {type(predictions)}")
        if hasattr(predictions, 'shape'):
            logger.info(f"Predictions shape: {predictions.shape}")
        
        return predictions
        
    except Exception as e:
        logger.error(f"Error during inference: {str(e)}")
        raise

def generate_trading_signals(predictions, inference_data, processed_data):
    """
    Generate trading signals from model predictions
    Adapt this based on what your model actually predicts
    """
    try:
        signals = []
        currencies = inference_data['currencies']
        currency_values = processed_data['currency_values']
        
        logger.info(f"Generating signals for {len(currencies)} currencies")
        
        # Map predictions to currency pairs
        # This depends on your model's output format
        
        edge_idx = 0
        signals_generated = 0
        
        for i, curr1 in enumerate(currencies):
            for j, curr2 in enumerate(currencies):
                if i != j:
                    # Get prediction for this edge
                    if hasattr(predictions, '__getitem__'):
                        pred_value = predictions[edge_idx] if edge_idx < len(predictions) else 0.0
                    else:
                        pred_value = 0.0  # Fallback
                    
                    edge_idx += 1
                    
                    # Convert to scalar if it's an array
                    if hasattr(pred_value, 'item'):
                        pred_value = pred_value.item()
                    elif isinstance(pred_value, (list, np.ndarray)):
                        pred_value = float(pred_value[0]) if len(pred_value) > 0 else 0.0
                    
                    # Generate signal based on prediction threshold
                    confidence = abs(pred_value)
                    if confidence > 0.005:  # 0.5% threshold, adjust as needed
                        signal = {
                            'signal_id': f"{curr1}_{curr2}_{int(datetime.utcnow().timestamp())}",
                            'pair': f"{curr1}/{curr2}",
                            'action': 'BUY' if pred_value > 0 else 'SELL',
                            'confidence': float(confidence),
                            'predicted_return': float(pred_value),
                            'base_currency': curr1,
                            'quote_currency': curr2,
                            'current_rate': float(currency_values[curr1] / currency_values[curr2]),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_version': 'arbitrage_gnn_v2'
                        }
                        signals.append(signal)
                        signals_generated += 1
        
        logger.info(f"Generated {signals_generated} trading signals out of {edge_idx} possible pairs")
        return signals
        
    except Exception as e:
        logger.error(f"Error generating signals: {str(e)}")
        raise

def save_signals_to_dynamodb(signals, date_str):
    """
    Save trading signals to DynamoDB
    """
    try:
        table = dynamodb.Table(SIGNALS_TABLE)
        
        with table.batch_writer() as batch:
            for signal in signals:
                item = {
                    'timestamp': int(datetime.utcnow().timestamp()),
                    'signal_id': signal['signal_id'],
                    'date': date_str,
                    'signal_data': signal,
                    'created_at': datetime.utcnow().isoformat(),
                    'model_version': signal.get('model_version', 'arbitrage_gnn_v2')
                }
                batch.put_item(Item=item)
        
        logger.info(f"Saved {len(signals)} signals to DynamoDB table: {SIGNALS_TABLE}")
        
    except Exception as e:
        logger.error(f"Error saving to DynamoDB: {str(e)}")
        raise

def lambda_handler(event, context):
    """
    ECR-based GNN Inference and Signal Generation
    """
    logger.info("Starting ECR GNN Inference Pipeline with arbitrage_gnn_v2.pt")
    
    try:
        # Load the latest processed data
        today = datetime.utcnow().strftime('%Y-%m-%d')
        processed_key = f"processed/{today}/analysis.json"
        
        try:
            response = s3_client.get_object(Bucket=PROCESSED_BUCKET, Key=processed_key)
            processed_data = json.loads(response['Body'].read().decode('utf-8'))
            logger.info(f"Loaded processed data for: {today}")
        except Exception as e:
            logger.warning(f"No data for {today}, searching for latest...")
            objects = s3_client.list_objects_v2(Bucket=PROCESSED_BUCKET, Prefix="processed/")
            if 'Contents' not in objects:
                raise Exception("No processed data available")
            
            latest = max(objects['Contents'], key=lambda x: x['LastModified'])
            response = s3_client.get_object(Bucket=PROCESSED_BUCKET, Key=latest['Key'])
            processed_data = json.loads(response['Body'].read().decode('utf-8'))
            today = latest['Key'].split('/')[1]
            logger.info(f"Using latest data from: {today}")
        
        # Load trained GNN model
        model = load_trained_model()
        
        # Prepare data for inference
        inference_data = prepare_inference_data(processed_data)
        
        # Run GNN inference
        predictions = run_gnn_inference(model, inference_data)
        
        # Generate trading signals
        trading_signals = generate_trading_signals(predictions, inference_data, processed_data)
        
        # Save signals to DynamoDB
        save_signals_to_dynamodb(trading_signals, today)
        
        # Save inference results to S3 for audit
        inference_results = {
            'inference_timestamp': datetime.utcnow().isoformat(),
            'date_processed': today,
            'model_used': MODEL_PATH,
            'signals_generated': len(trading_signals),
            'currencies_processed': len(inference_data['currencies']),
            'prediction_stats': {
                'mean': float(np.mean(predictions)) if hasattr(predictions, 'mean') else 0.0,
                'std': float(np.std(predictions)) if hasattr(predictions, 'std') else 0.0,
                'min': float(np.min(predictions)) if hasattr(predictions, 'min') else 0.0,
                'max': float(np.max(predictions)) if hasattr(predictions, 'max') else 0.0
            },
            'model_info': {
                'path': MODEL_PATH,
                'parameters': sum(p.numel() for p in model.parameters()) if hasattr(model, 'parameters') else 'unknown'
            }
        }
        
        results_key = f"inference/{today}/v2_results_{int(datetime.utcnow().timestamp())}.json"
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=results_key,
            Body=json.dumps(inference_results, indent=2),
            ContentType='application/json'
        )
        
        logger.info("ECR Inference Pipeline completed successfully")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'ECR GNN Inference completed successfully',
                'model_used': MODEL_PATH,
                'signals_generated': len(trading_signals),
                'date_processed': today,
                'dynamodb_table': SIGNALS_TABLE,
                'inference_results': f"s3://{PROCESSED_BUCKET}/{results_key}",
                'currencies_processed': len(inference_data['currencies'])
            })
        }
        
    except Exception as e:
        logger.error(f"ECR Inference Pipeline failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'ECR Inference Pipeline failed: {str(e)}'})
        }
