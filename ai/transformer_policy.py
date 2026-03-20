import torch
import torch.nn as nn
import numpy as np


class TransformerPolicy(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim=128, num_heads=4, num_layers=2):
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim

        # Simple transformer for policy
        self.embedding = nn.Linear(state_dim, hidden_dim)
        self.transformer = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(hidden_dim, num_heads, batch_first=True),
            num_layers
        )
        self.policy_head = nn.Linear(hidden_dim, action_dim)
        self.value_head = nn.Linear(hidden_dim, 1)

    def forward(self, state):
        # state: (batch, seq_len, state_dim) or (batch, state_dim)
        if state.dim() == 2:
            state = state.unsqueeze(1)  # Add seq dim
        x = self.embedding(state)
        x = self.transformer(x)
        x = x.mean(dim=1)  # Pool over sequence
        logits = self.policy_head(x)
        value = self.value_head(x)
        return logits, value.squeeze(-1)


class RLAgent:
    def __init__(self, state_dim=5, action_dim=10):  # Assuming 5 state dims, 10 actions
        self.policy = TransformerPolicy(state_dim, action_dim)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=1e-3)
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.action_space = []  # List of possible actions
        self.behavior_graph = {}  # Behavior graph from editor

    def set_behavior_graph(self, graph):
        self.behavior_graph = graph

    def act(self, state):
        """Select an action given state."""
        if self.action_space:
            self.action_dim = len(self.action_space)
            # Reinitialize policy if action_dim changed
            if self.policy.action_dim != self.action_dim:
                self.policy = TransformerPolicy(self.state_dim, self.action_dim)
        # If behavior graph exists, use it to guide action
        if self.behavior_graph:
            # Simple logic: if "Click Action" is connected to "Has Enough Gold", and gold > 100, prefer click
            if "Click Action" in self.behavior_graph and "Has Enough Gold" in self.behavior_graph["Click Action"]:
                if state[1] > 100:  # Assuming state[1] is gold
                    return 0  # Assume 0 is click
        state = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            logits, _ = self.policy(state)
            probs = torch.softmax(logits, dim=-1)
            action = torch.multinomial(probs, 1).item()
        return action

    def train_step(self, states, actions, rewards, next_states):
        """Simple training step (placeholder)."""
        # For now, just a dummy train
        pass