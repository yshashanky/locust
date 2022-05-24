import time
from locust import HttpUser, task, between, User, constant

#Sample code 1:
# class QuickstartUser(HttpUser):
#     wait_time = between(1, 5)

#     @task
#     def hello_world(self):
#         self.client.get("/")
#         self.client.get("/world")

#     @task(3)
#     def view_items(self):
#         for item_id in range(10):
#             self.client.get(f"/item?id={item_id}", name="/item")
#             time.sleep(1)

#     def on_start(self):
#         self.client.post("/", json={"username":"", "password":""}) 
        
#Sample code 2:

class MyFirstTest(User):
    weight = 2
    wait_time = constant(1)

    @task
    def launch(self):
        print("Launching the URL")

    @task
    def search(self):
        print("Searching")

class MySecondTest(User):
    weight = 2
    wait_time = constant(1)
    
    @task
    def launch2(self):
        print("Second test")

    @task 
    def search2(self):
        print("Second search test")