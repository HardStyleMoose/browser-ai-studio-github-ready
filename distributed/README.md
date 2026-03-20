# Distributed Training Setup for BrowserAI Studio

## Requirements
- Install Ray:
  ```
  pip install ray
  ```

## How It Works
- Each worker runs an InputManager and executes the current behavior graph in parallel.
- You can scale up the number of workers for faster training or evaluation.

## Usage
- Edit `distributed/distributed_training_example.py` to load your actual behavior graph.
- Run distributed training:
  ```
  python distributed/distributed_training_example.py
  ```
- Results from all workers will be printed at the end.

## Integration
- You can extend this to synchronize model weights, share experience, or aggregate results using Ray's actor and object store features.
- For advanced use, connect the distributed workers to your main UI or cluster dashboard.

## Troubleshooting Distributed Training
- Ensure Ray is installed and working (`pip show ray`).
- If workers fail to start, check for port conflicts or missing dependencies.
- Use `ray.init(ignore_reinit_error=True)` for local testing.
- Monitor resource usage with Ray Dashboard (`ray dashboard`).

## Advanced Integration Tips
- Use Ray actors for persistent worker state and communication.
- Aggregate rewards and logs using Ray's object store.
- Connect distributed workers to the main UI via sockets or REST API for real-time updates.
- For large-scale training, configure Ray cluster resources and autoscaling.

## Example: Launch Ray Dashboard
```
ray dashboard
```

---

This setup provides a foundation for distributed RL or imitation learning workflows in BrowserAI Studio.
