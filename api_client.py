import requests

BASE_URL = "http://192.168.120.200"

def fetch_topic_info(topic_name: str) -> dict:
    """
    Returns a dict with all topic metadata from the /topics endpoint:
      - 'name':            the topic name
      - 'schema':          the raw Avro schema dict
      - 'bootstrapServers':the Kafka bootstrap.servers string
    """
    resp = requests.get(f"{BASE_URL}/topics", params={"name": topic_name})
    resp.raise_for_status()
    data = resp.json()
    return {
        "name": data.get("name"),
        "schema": data.get("schema"),
        "bootstrapServers": data.get("bootstrapServers")
    }