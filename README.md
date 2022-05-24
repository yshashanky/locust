# locust
Starting with locust:
- Learning series: https://www.youtube.com/playlist?list=PLJ9A48W0kpRKMCzJARCObgJs3SinOewp5
- Main file:  create a python file
- To run with the web UI, run with following command: locust or locust -f filename.py
- For direct command line usage use: locust --headless --users 10 --spawn-rate 1 -H https://oceanready-personalinfo-ui.prod.ocean.com/ {http://your-server.com}
- To terminate locust: ctrl+c
- Locust web UI runs on localhost:8089

Terminologies:
- Swarm: A group travelling in same direction
- Hatching: Production
- Spwan: Release or deposite 
- greenlet: creates micro threads

Locust classes:
- User:
    - abstract=True
    - on_start()
    - on_stop()
    - tasks
    - wait()
    - wait_time()
    - weight=10
- HttpUser
    - It creates 'client', an instance of HttpSession
    - GET, POST, PUT, DELETE, HEAD, headers, text, status_code, etc.
- TaskSet
- SequentialTaskSet
- HttpSession
- Response
- ResponseContextManager
- Environment
- Runner
- WebUI