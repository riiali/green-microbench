from locust import HttpUser, task, between
import uuid, random, os

def get_seed():
    try:
        return int(os.getenv("LOCUST_SEED", ""))
    except Exception:
        return None

class HostUser(HttpUser):
    wait_time = between(2, 4)

    def on_start(self):
        seed = get_seed()
        if seed is not None:
            random.seed(seed)

    @task
    def add_apartment(self):
        apartment_id = str(uuid.uuid4())[:8]
        payload = {
            "name": f"Appartamento-{apartment_id}",
            "address": f"Via Test {random.randint(1, 100)}",
            "noiselevel": random.randint(1, 10),
            "floor": random.randint(0, 5),
        }
        headers = {"Content-Type": "application/json"}
        with self.client.post("/apartment/add", json=payload, headers=headers, name="/apartment/add", catch_response=True) as r:
            try:
                r.raise_for_status()
            except Exception as e:
                r.failure(str(e))
