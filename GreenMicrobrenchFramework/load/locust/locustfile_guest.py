from locust import HttpUser, task, between
from datetime import datetime, timedelta
import random, uuid, os, time
from contextlib import contextmanager

REFRESH_APTS_EVERY_SEC = 30

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

class GuestUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        seed = get_seed()
        if seed is not None:
            random.seed(seed + hash(self.environment.runner.client_id) % 100000)
        self.booking_ids = []
        self.apartments = []
        self._last_apts_refresh = 0
        self.update_available_apartments()

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

    @task(5)
    def do_search(self):
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=2)
        self.update_available_apartments()
        with req(self.client, "GET", f"/search/search?from={start_date}&to={end_date}", name="/search/search"):
            pass

    @task(3)
    def search_and_book(self):
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=2)
        self.update_available_apartments()
        if not self.apartments:
            return

        apartment_id = random.choice(self.apartments)
        who = str(uuid.uuid4())

        payload = {
            "apartment_id": apartment_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "who": who,
        }
        headers = {"Content-Type": "application/json"}
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
            payload_change = {"id": booking_id, "start_date": str(start_date), "end_date": str(new_end)}
            with req(self.client, "PUT", "/booking/change", json=payload_change, headers=headers, name="/booking/change"):
                pass

        if self.booking_ids and random.random() < 0.3:
            booking_id = random.choice(self.booking_ids)
            with req(self.client, "DELETE", f"/booking/cancel?id={booking_id}", name="/booking/cancel"):
                try:
                    self.booking_ids.remove(booking_id)
                except ValueError:
                    pass
