# locust
Starting with locust:
- Learning series: https://www.youtube.com/playlist?list=PLJ9A48W0kpRKMCzJARCObgJs3SinOewp5
- Main file:  locustfile.py
- To run with the web UI, run with following command: locust
- For direct command line usage use: locust --headless --users 10 --spawn-rate 1 -H https://oceanready-personalinfo-ui.prod.ocean.com/ {http://your-server.com}


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
- TaskSet
- SequentialTaskSet
- HttpSession
- Response
- ResponseContextManager
- Environment
- Runner
- WebUI