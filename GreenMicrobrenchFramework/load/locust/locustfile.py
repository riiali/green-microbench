from locust import HttpUser, task, between
from datetime import datetime, timedelta
from contextlib import contextmanager
import random, uuid, os, time

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

        # Wait until apartments exist
        while not self.apartments:
            self.update_available_apartments(force=True)
            if not self.apartments:
                time.sleep(1)

    def update_available_apartments(self, force=False):
        now = time.time()
        if not force and (now - self._last_apts_refresh) < REFRESH_APTS_EVERY_SEC:
            return

        with req(self.client, "GET", "/booking/listavailableappartments",
                 name="/booking/listavailableappartments") as r:
            try:
                data = r.json()
                self.apartments = [a[1] for a in data.get("available_appartments", [])]
            except:
                self.apartments = []

        self._last_apts_refresh = now

    @task(5)
    def search(self):
        start = datetime.now().date()
        end = start + timedelta(days=2)
        self.update_available_apartments()

        with req(self.client, "GET",
                 f"/search/search?from={start}&to={end}", name="/search/search"):
            pass

    @task(3)
    def book_flow(self):
        start = datetime.now().date()
        end = start + timedelta(days=2)
        self.update_available_apartments()

        if not self.apartments:
            return

        apt_id = random.choice(self.apartments)
        who = str(uuid.uuid4())

        payload = {
            "apartment_id": apt_id,
            "start_date": str(start),
            "end_date": str(end),
            "who": who,
        }
        headers = {"Content-Type": "application/json"}

        # Add booking
        with req(self.client, "POST", "/booking/add", json=payload,
                 headers=headers, name="/booking/add") as r:
            try:
                booking_id = r.json().get("id")
                if booking_id:
                    self.booking_ids.append(booking_id)
            except:
                return

        # Change booking
        if self.booking_ids and random.random() < 0.3:
            booking_id = random.choice(self.booking_ids)
            new_end = end + timedelta(days=2)
            change_payload = {
                "id": booking_id,
                "start_date": str(start),
                "end_date": str(new_end)
            }
            with req(self.client, "PUT", "/booking/change", json=change_payload,
                     headers=headers, name="/booking/change"):
                pass

        # Cancel booking
        if self.booking_ids and random.random() < 0.3:
            booking_id = random.choice(self.booking_ids)
            with req(self.client, "DELETE",
                     f"/booking/cancel?id={booking_id}", name="/booking/cancel"):
                try:
                    self.booking_ids.remove(booking_id)
                except:
                    pass


class HostUser(HttpUser):
    wait_time = between(2, 4)

    def on_start(self):
        seed = get_seed()
        if seed is not None:
            random.seed(seed)

    @task
    def add_apartment(self):
        apt_id = str(uuid.uuid4())[:8]
        payload = {
            "name": f"Apartment-{apt_id}",
            "address": f"Street {random.randint(1, 100)}",
            "noiselevel": random.randint(1, 10),
            "floor": random.randint(0, 5),
        }
        headers = {"Content-Type": "application/json"}

        with self.client.post("/apartment/add", json=payload,
                              headers=headers, name="/apartment/add",
                              catch_response=True) as r:
            try:
                r.raise_for_status()
            except Exception as e:
                r.failure(str(e))
