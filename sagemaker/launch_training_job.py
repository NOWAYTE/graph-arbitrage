# sagemaker/launch_training_job.py
import sagemaker
from sagemaker.pytorch import PyTorch

session = sagemaker.Session()
role = "arn:aws:iam::852815611756:role/service-role/AmazonSageMaker-ExecutionRole"

estimator = PyTorch(
    entry_point="train_gnn.py",
    source_dir="../training",
    role=role,
    framework_version="2.1",
    py_version="py310",
    instance_type="ml.m5.xlarge",
    instance_count=1,
    hyperparameters={
        "epochs": 25,
        "batch_size": 8,
        "lr": 1e-3,
    },
    output_path="s3://graph-arbitrage-processed-data-se/models/",
    base_job_name="graph-arbitrage-train",
)

estimator.fit({"train": "s3://graph-arbitrage-processed-data-se/processed/daily/"})

