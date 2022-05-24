import time
from locust import HttpUser, task, between, User, constant

#Sample HttpUser Class:

class MyReqRes(HttpUser):

    host = "https://regres.in"
    #wait_time = between(1, 5)
    wait_time = constant(1)

    @task
    def get_users(self):
        res = self.client.get("/api/users?page=2")
        print(res.text)
        print(res.status_code)
        print(res.headers)

    @task
    def create_users(self):
        res = self.client.post("/api/users", data=''' 
            {"name":"morpheus","job":"leader"}
        ''')
        print(res.text)
        print(res.status_code)
        print(res.headers)

    # @task
    # def view_items(self):
    #     for item_id in range(10):
    #         self.client.get(f"/item?id={item_id}", name="/item")
    #         time.sleep(1)

    # def on_start(self):
    #     self.client.post("/", json={"username":"", "password":""}) 
        

#Sample User Class:

# class MyFirstTest(User):
#     weight = 2
#     wait_time = constant(1)

#     @task
#     def launch(self):
#         print("Launching the URL")

#     @task
#     def search(self):
#         print("Searching")

# class MySecondTest(User):
#     weight = 2
#     wait_time = constant(1)

#     @task
#     def launch2(self):
#         print("Second test")

#     @task 
#     def search2(self):
#         print("Second search test")