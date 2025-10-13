FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

RUN pip install torch-geometric networkx pandas scikit-learn boto3

COPY train_gnn.py /opt/ml/code/train_gnn.py
ENTRYPOINT ["python", "/opt/ml/code/train_gnn.py"]

