# training/train_gnn.py
import os, argparse, json, torch
from torch_geometric.data import DataLoader
from model import GraphArbitrageGNN  # your GNN architecture
from dataset import ArbitrageDataset

def train(args):
    # Load dataset
    dataset = ArbitrageDataset(root=args.input_data)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)

    # Initialize model
    model = GraphArbitrageGNN(num_features=dataset.num_features, hidden_dim=64)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = torch.nn.MSELoss()

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0
        for batch in loader:
            optimizer.zero_grad()
            out = model(batch.x, batch.edge_index)
            loss = criterion(out, batch.y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        print(f"Epoch {epoch+1}/{args.epochs} - Loss: {total_loss/len(loader):.6f}")

    # Save model
    model_dir = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
    os.makedirs(model_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(model_dir, "graph_gnn.pt"))

    print("✅ Model saved to", model_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_data", type=str, default=os.environ.get("SM_CHANNEL_TRAIN"))
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    train(args)
