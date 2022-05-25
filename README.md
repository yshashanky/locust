# locust
## Starting with locust:
- Learning series: https://www.youtube.com/playlist?list=PLJ9A48W0kpRKMCzJARCObgJs3SinOewp5
- Main file:  create a python file
- To run with the web UI, run with following command: locust or locust -f filename.py
- For direct command line usage use: locust --headless --users 10 --spawn-rate 1 -H https://oceanready-personalinfo-ui.prod.ocean.com/ {http://your-server.com}
- To terminate locust: ctrl+c
- Locust web UI runs on localhost:8089
- Without user class locust will not run
- Tasks are picked randomly in locust

## Terminologies:
- Swarm: A group travelling in same direction
- Hatching: Production
- Spwan: Release or deposite 
- greenlet: creates micro threads

## Locust classes:
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
    - Picks up a task -> Execute it -> wait_time
    - Taskset can be nested, client, interrupt
    - When taskset is nested, it did not come to parent class again from the nested class to make it happen we need to use self.interrupt function 
    - When two or more taskset classes are defined, if one class is picked then it will not go to another class, to make it happen we need to use self.interrupt function with every class
    - self.interrupt: on default reshedule will be True
    - self.interrupt(reshedule=True): it will go instantly to the parent class
    - self.interrupt(reshedule=False): it will after the wait time to the parent class
    - on_start(), on_stop(), parent, tasks, user
    - wait(), wait_time()

- SequentialTaskSet
    - define the task in sequential order
    - task weight will be ignored
    - client, interrupt(reschedule=True)
    - on_start(), on_stop(), parent, user
    - schedule_task(task_callable,first=false), wait_time()

- wait_time function
    - unit is seconds
    - between(min, max)
    - constant(wait time)
    - constant_pacing(wait time)

- on_start and on_stop method
    - Don't use @task decorator for these methods
    - It executes only once

- HttpSession
- Response
- ResponseContextManager
- Environment
- Runner
- WebUI

## Command line options:
- Runtime:
    - locust -h: gives all the commands
    - locust -f filename.py -u 1 -r 1 -t 10s --headless --print-stats --csv Run1.csv --csv-full-history --host=https://example.com
        - -f filename.py: give the path of file to run
        - -u 1: give no. of users here; it is one
        - -r 1: give spwan rate here; it is one
        - -t 10s: give duration for which test will run; 10sec is duration here (h: hour, m:min, s:seconds)
        - headless: webUI will not be started everything will be printed in UI
        - --print-stats: print all statics in terminal
        - --csv Run1.csv --csv-full-history: use to store all the stats in csv file
        - --host=https://example.com: give address of host here
        - --only-summary: prints only summary in terminal

- Log, Stats
    - locust -f filename.py -u 1 -r 1 -t 10s --headless --print-stats --csv Run1.csv --csv-full-history --host=https://example.com -L CRITICAL --logfile mylog.log --html Run1
        - -L CRITICAL: level of info we want to log; options are: DEBUG/INFO/WARNING/ERROR/CRITICAL
        - --logfile mylog.log: create log file with given name
        - --html Run1: create HTML report with given name
    - locust -f filename.py -l: Lists all the user classes
    - locust -f filename.py --show-task-ratio: print the task execution ratio; prints in table format
    - locust -f filename.py --show-task-ratio-json: print task execution ratio in json format

- WEB UI, Master & Worker, Tag, etc.

### Validating responses:
- even response code is 200, doesn't mean it is success, validating response is important
- catch_response=True
- response.success()
- response.failure()
    - eg: with self.client.get("/xml", catch_response=True, name="XML")as response:
        if response.status_code == 200 and "WonderWidgets"in response.text:
            print("XML")
            response.success()
        else:
            response.failure("Failed XML request")

### Data parameterization:
- testing with multiple set of data
- test data in seperate file/python file/third party library