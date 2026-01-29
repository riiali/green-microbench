from locust import HttpUser, task, between
from datetime import datetime, timedelta
from contextlib import contextmanager
import uuid
import random
import os
import time

REFRESH_APTS_EVERY_SEC = 30
MIN_INITIAL_APTS = 3

def get_seed():
    try:
        return int(os.getenv("LOCUST_SEED", ""))
    except Exception:
        return None

@contextmanager
def req(client, method, url, **kwargs):
    name = kwargs.pop("name", url)
    with client.request(method, url, name=name, catch_response=True, **kwargs) as r:
        try:
            r.raise_for_status()
            yield r
        except Exception as e:
            r.failure(str(e))
            raise

class User(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        seed = get_seed()
        if seed is not None:
            offset = hash(getattr(self.environment.runner, "client_id", 0)) % 100000
            random.seed(seed + offset)

        self.booking_ids = []
        self.apartments = []
        self._last_apts_refresh = 0

        # First action: create at least 3 apartments
        for _ in range(MIN_INITIAL_APTS):
            self.add_apartment()

        self.update_available_apartments(force=True)

    def update_available_apartments(self, force=False):
        now = time.time()
        if not force and (now - self._last_apts_refresh) < REFRESH_APTS_EVERY_SEC:
            return
        with req(self.client, "GET", "/booking/listavailableappartments", name="/booking/listavailableappartments") as r:
            try:
                data = r.json()
                self.apartments = [a[1] for a in data.get("available_appartments", [])]
            except Exception as e:
                r.failure(f"JSON decode error: {e}")
                self.apartments = []
        self._last_apts_refresh = now

    @task(2)
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
                return

    @task(65)
    def search(self):
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=2)
        self.update_available_apartments()
        with req(self.client, "GET", f"/search/search?from={start_date}&to={end_date}", name="/search/search"):
            pass

    @task(33)
    def search_and_book(self):
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=2)
        self.update_available_apartments()

        if not self.apartments:
            return

        apartment_id = random.choice(self.apartments)
        who = str(uuid.uuid4())
        headers = {"Content-Type": "application/json"}

        payload = {
            "apartment_id": apartment_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "who": who,
        }

        with req(self.client, "POST", "/booking/add", json=payload, headers=headers, name="/booking/add") as r:
            try:
                booking_id = r.json().get("id")
                if booking_id:
                    self.booking_ids.append(booking_id)
            except Exception as e:
                r.failure(f"JSON decode error: {e}")
                return

        if self.booking_ids and random.random() < 0.3:
            booking_id = random.choice(self.booking_ids)
            new_end = end_date + timedelta(days=2)
            payload_change = {
                "id": booking_id,
                "start_date": str(start_date),
                "end_date": str(new_end),
            }
            with req(self.client, "PUT", "/booking/change", json=payload_change, headers=headers, name="/booking/change"):
                pass

        if self.booking_ids and random.random() < 0.3:
            booking_id = random.choice(self.booking_ids)
            with req(self.client, "DELETE", f"/booking/cancel?id={booking_id}", name="/booking/cancel"):
                try:
                    self.booking_ids.remove(booking_id)
                except ValueError:
                    pass
