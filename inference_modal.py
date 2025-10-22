import os
import json
import logging
from datetime import datetime, timedelta
import modal

app = modal.App("graph-arbitrage-inference")

image = (
    modal.Image.debian_slim()
    .pip_install(
        "boto3",
        "torch",
        "torch-geometric",
        "numpy",
        "pandas",
    )
)

secrets = [modal.Secret.from_name("aws-creds")]


@app.function(image=image, secrets=secrets, timeout=900)
def run_inference_modal():
    from decimal import Decimal
    import io
    import traceback
    import boto3
    import numpy as np
    import torch
    import torch.nn as nn
    from torch_geometric.nn import GCNConv, global_mean_pool

    logger = logging.getLogger("modal_inference")
    logger.setLevel(logging.INFO)

    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    aws_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    s3_client = boto3.client("s3", region_name=aws_region)
    dynamodb = boto3.resource("dynamodb", region_name=aws_region)

    PROCESSED_BUCKET = "graph-arbitrage-processed-data-se"
    MODELS_BUCKET = "graph-arbitrage-models"
    SIGNALS_TABLE = "fx-signals"
    MODEL_PATH = "v2/arbitrage_gnn_v2.pt"

    class ArbitrageGNNv2(nn.Module):
        def __init__(self, node_dim=2, hidden_dim=64):
            super().__init__()
            self.conv1 = GCNConv(node_dim, hidden_dim)
            self.conv2 = GCNConv(hidden_dim, hidden_dim)
            self.fc_class = nn.Sequential(
                nn.Linear(hidden_dim, 32), nn.ReLU(), nn.Linear(32, 1), nn.Sigmoid()
            )
            self.fc_reg = nn.Sequential(
                nn.Linear(hidden_dim, 32), nn.ReLU(), nn.Linear(32, 1)
            )

        def forward(self, x, edge_index, batch):
            x = torch.relu(self.conv1(x, edge_index))
            x = torch.relu(self.conv2(x, edge_index))
            pooled = global_mean_pool(x, batch)
            return self.fc_class(pooled), self.fc_reg(pooled)

    def download_processed_data_for_latest_day():
        today = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        processed_key = f"processed/historical/{today}/analysis.json"
        try:
            resp = s3_client.get_object(Bucket=PROCESSED_BUCKET, Key=processed_key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
            logger.info(f"Loaded processed data for: {today}")
            return today, data
        except Exception:
            logger.warning(f"No data for {today}, searching for latest...")
            objects = s3_client.list_objects_v2(Bucket=PROCESSED_BUCKET, Prefix="processed/")
            if "Contents" not in objects or len(objects["Contents"]) == 0:
                raise RuntimeError("No processed data available in processed/ prefix")
            latest = max(objects["Contents"], key=lambda x: x["LastModified"])
            resp = s3_client.get_object(Bucket=PROCESSED_BUCKET, Key=latest["Key"])
            data = json.loads(resp["Body"].read().decode("utf-8"))
            day = latest["Key"].split("/")[1]
            logger.info(f"Using latest processed data from: {day} (key: {latest['Key']})")
            return day, data

    def load_trained_model():
        local_path = f"/tmp/{os.path.basename(MODEL_PATH)}"
        if not os.path.exists(local_path):
            logger.info(f"Downloading model from S3: s3://{MODELS_BUCKET}/{MODEL_PATH}")
            s3_client.download_file(MODELS_BUCKET, MODEL_PATH, local_path)
            logger.info(f"Model downloaded to {local_path}")
        model = ArbitrageGNNv2()
        loaded = torch.load(local_path, map_location=torch.device("cpu"))
        import collections
        if isinstance(loaded, collections.OrderedDict) or isinstance(loaded, dict):
            model.load_state_dict(loaded)
        else:
            try:
                model = loaded
            except Exception:
                model = ArbitrageGNNv2()
                model.load_state_dict(loaded.state_dict())
        model.eval()
        return model

    def prepare_inference_data(processed_data):
        import torch
        import numpy as np

        if "processed_days" not in processed_data or not processed_data["processed_days"]:
            raise KeyError("No processed_days found in processed data")

        latest_day = processed_data["processed_days"][-1]
        currency_values = latest_day.get("currency_values", {})

        if not currency_values:
            raise KeyError("currency_values not found in the latest processed day")

        currencies = sorted(list(currency_values.keys()))
        logger.info(f"Preparing inference data for {len(currencies)} currencies: {currencies}")

        node_features = []
        for currency in currencies:
            value = currency_values[currency]
            if isinstance(value, dict):
                features = [float(v) for v in value.values()]
            else:
                features = [float(value)]
            if len(features) < 2:
                features.append(0.0)
            elif len(features) > 2:
                features = features[:2]
            node_features.append(features)

        edge_index = []
        edge_attributes = []

        for i in range(len(currencies)):
            for j in range(len(currencies)):
                if i != j:
                    edge_index.append([i, j])
                    rate = currency_values[currencies[i]]["mid"] / currency_values[currencies[j]]["mid"] \
                        if isinstance(currency_values[currencies[i]], dict) else \
                        currency_values[currencies[i]] / currency_values[currencies[j]]
                    edge_attributes.append([rate])

        node_tensor = torch.tensor(node_features, dtype=torch.float32)
        edge_tensor = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        edge_attr_tensor = torch.tensor(edge_attributes, dtype=torch.float32)

        inference_data = {
            "x": node_tensor,
            "edge_index": edge_tensor,
            "edge_attr": edge_attr_tensor,
            "currencies": currencies,
        }

        logger.info(f"Prepared {len(currencies)} currencies and {len(edge_index)} edges for inference.")
        return inference_data

    def run_gnn_inference(model, inference_data):
        with torch.no_grad():
            batch = torch.zeros(inference_data["x"].size(0), dtype=torch.long)
            class_out, reg_out = model(inference_data["x"], inference_data["edge_index"], batch)
            preds = reg_out.squeeze()
            if preds.ndim == 0:
                preds = preds.unsqueeze(0)
            preds = preds.cpu().numpy()
        return preds

    def generate_trading_signals(predictions, inference_data, processed_data):
        signals = []
        currencies = inference_data["currencies"]
        currency_values = processed_data["processed_days"][-1]["currency_values"]
        edge_idx = 0
        signals_generated = 0
        for i, curr1 in enumerate(currencies):
            for j, curr2 in enumerate(currencies):
                if i != j:
                    pred_value = predictions[edge_idx] if edge_idx < len(predictions) else 0.0
                    edge_idx += 1
                    if hasattr(pred_value, "item"):
                        pred_value = pred_value.item()
                    elif isinstance(pred_value, (list, np.ndarray)):
                        pred_value = float(pred_value[0]) if len(pred_value) > 0 else 0.0
                    confidence = abs(pred_value)
                    if confidence > 0.005:
                        signal = {
                            "signal_id": f"{curr1}_{curr2}_{int(datetime.utcnow().timestamp())}",
                            "pair": f"{curr1}/{curr2}",
                            "action": "BUY" if pred_value > 0 else "SELL",
                            "confidence": float(confidence),
                            "predicted_return": float(pred_value),
                            "base_currency": curr1,
                            "quote_currency": curr2,
                            "current_rate": float(currency_values[curr1] / currency_values[curr2]),
                            "timestamp": datetime.utcnow().isoformat(),
                            "model_version": "arbitrage_gnn_v2",
                        }
                        signals.append(signal)
                        signals_generated += 1
        logger.info(f"Generated {signals_generated} trading signals out of {edge_idx} pairs")
        return signals


    def convert_floats_to_decimal(obj):
        """Recursively convert all float values to decimal"""
        if isinstance(obj, list):
            return [convert_floats_to_decimal(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, float):
            return Decimal(str(obj))
        else:
            return obj

    def save_signals_to_dynamodb(signals, date_str):
        if len(signals) == 0:
            logger.info("No signals to save to DynamoDB")
            return
        table = dynamodb.Table(SIGNALS_TABLE)
        with table.batch_writer() as batch:
            for signal in signals:

                signal_decimal = convert_floats_to_decimal(signal)
                item = {
                    "timestamp": int(datetime.utcnow().timestamp()),
                    "signal_id": signal["signal_id"],
                    "date": date_str,
                    "signal_data": signal_decimal,
                    "created_at": datetime.utcnow().isoformat(),
                    "model_version": signal.get("model_version", "arbitrage_gnn_v2"),
                }
                batch.put_item(Item=item)
        logger.info(f"Saved {len(signals)} signals to DynamoDB table: {SIGNALS_TABLE}")

    try:
        date_processed, processed_data = download_processed_data_for_latest_day()
        model = load_trained_model()
        inference_data = prepare_inference_data(processed_data)
        predictions = run_gnn_inference(model, inference_data)
        trading_signals = generate_trading_signals(predictions, inference_data, processed_data)
        save_signals_to_dynamodb(trading_signals, date_processed)

        inference_results = {
            "inference_timestamp": datetime.utcnow().isoformat(),
            "date_processed": date_processed,
            "model_used": MODEL_PATH,
            "signals_generated": len(trading_signals),
            "currencies_processed": len(inference_data["currencies"]) if "currencies" in inference_data else 0,
        }

        results_key = f"inference/{date_processed}/v2_results_{int(datetime.utcnow().timestamp())}.json"
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=results_key,
            Body=json.dumps(inference_results, indent=2),
            ContentType="application/json",
        )

        logger.info("Modal inference pipeline completed successfully")
        return {"status": "success", "s3_results": f"s3://{PROCESSED_BUCKET}/{results_key}", "signals": len(trading_signals)}

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Modal inference failed: {e}\n{tb}")
        return {"status": "error", "message": str(e), "traceback": tb}




if __name__ == "__main__":
    with app.run():
        result = run_inference_modal.remote()
        print("Inference result", result)
