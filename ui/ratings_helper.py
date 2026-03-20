import os
import json

def ratings_path(base_dir, name="ratings.json"):
    path = os.path.join(base_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

def load_ratings(base_dir):
    path = ratings_path(base_dir)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_ratings(base_dir, ratings):
    path = ratings_path(base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ratings, f, indent=2)

def get_ratings(ratings, item_name):
    return ratings.get(item_name, {"ratings": [], "comments": []})

def submit_rating(base_dir, item_name, stars, comment):
    ratings = load_ratings(base_dir)
    entry = ratings.setdefault(item_name, {"ratings": [], "comments": []})
    entry["ratings"].append(stars)
    if comment:
        entry["comments"].append(comment)
    save_ratings(base_dir, ratings)
    return ratings
