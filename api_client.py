import requests

BASE_URL = "http://192.168.120.35"

def fetch_topic_schema(topic_name: str) -> dict:
    """
    Returns the Avro schema dict for the given topic.
    """
    resp = requests.get(f"{BASE_URL}/topics", params={"name": topic_name})
    resp.raise_for_status()
    data = resp.json()
    return data["schema"]