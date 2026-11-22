import urllib3
from locust import HttpUser, task, between

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OpenBMCUser(HttpUser):
    host = "https://localhost:2443"
    wait_time = between(1, 3)

    def on_start(self):
        self.client.verify = False
        response = self.client.post(
            "/redfish/v1/SessionService/Sessions",
            json={"UserName": "root", "Password": "0penBmc"},
            name="OpenBMC: login",
        )
        token = response.headers.get("X-Auth-Token")
        self.client.headers.update({"X-Auth-Token": token})

    @task(3)
    def get_system_info(self):
        self.client.get(
            "/redfish/v1/Systems/system",
            name="OpenBMC: system info",
        )

    @task(2)
    def get_power_state(self):
        with self.client.get(
            "/redfish/v1/Systems/system",
            name="OpenBMC: power state",
            catch_response=True,
        ) as response:
            if response.status_code == 200 and "PowerState" in response.json():
                response.success()
            else:
                response.failure(f"Нет PowerState, код {response.status_code}")


class JsonPlaceholderUser(HttpUser):
    host = "https://jsonplaceholder.typicode.com"
    wait_time = between(1, 3)

    @task
    def get_posts(self):
        self.client.get("/posts", name="JSONPlaceholder: /posts")