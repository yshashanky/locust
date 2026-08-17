## Locust
### Starting with locust:
- Main file:  create a python file
- To run with the web UI, run with following command: locust or locust -f filename.py
- For direct command line usage use: locust --headless --users 10 --spawn-rate 1 -H {http://your-server.com}
- To terminate locust: ctrl+c
- Locust web UI runs on localhost:8089
- Without user class locust will not run
- Tasks are picked randomly in locust
-----
### Terminologies:
- Swarm: A group travelling in same direction
- Hatching: Production
- Spwan: Release or deposite 
- greenlet: creates micro threads
-----
### Locust classes:
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
-----
### Command line options:
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

- Tag
    - decorator for tagging tasks and tasksets
    - @tag('tagname', 'tagname', ...)
    - --tags tagname: used to run on tagged items
    - --exclude-tags tagname: used to exclude tagged items

- WEB UI, Master & Worker, etc.
-----
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
-----
### Data parameterization:
- testing with multiple set of data
- test data in seperate file/python file/third party library
-----
### Correlation in Locust
- extracting the dynamic value from the response
- pass the extracted value in the subsequent requests
- Regular expressions, parsers
-----
### Logging in Locust
- Logging helps to debug script, CI/CD etc
- --skip-log-setup: skip logging setup
- --logfile mylog.log
- --loglevel: DEBUG/INFO/WARNING/ERROR/CRITICAL
- eg: import logging
    - logging.info()
    - logging.error()
    - logging.critical()
    - logging.debug()
    - logging.warning()
-----
### Configuration of Locust
- Command line eg. -host, -u, -r
- https://docs.locust.io/en/latest/configuration.html#environment-variables
- Environment Variables:
    - LOCUST_HOST
    - LOCUST_USERS
    - LOCUST_SPAWN_RATE
    - LOCUST_HEADLESS
    - LOCUST_TAGS
    - LOCUST_MODE_MASTER
    - etc...
- Configuration file
    - name.conf or name.yaml
    - eg. name.conf file
        - [runtime settings]
        - host=http://example.com
        - users=2
        - spawn-rate=1
        - run-time=5s
        - headless=true
        - only-summary=true
    - eg. name.yaml file
        - #Runtime Settings
        - host:https://httpbin.org
        - users:2
        - spawn-rate:1
        - run-time:5s
        - headless:true
        - only-summary:true
- Override Order(Priority to check conf)
    - ~/locust.conf in Home dir
    - ./locust.conf in Current dir
    - file specified using --conf
    - env variables
    - command line arguments
-----
### Events and EventHook
- Events
    - a thing that happens,especially one of importance
    - In Locust,you can do tasks at certain circumstances using the Event Hooks
    - e.g.,before starting the test,during the test,or after the test
    - test_start
    - test_stop
    - on_locust_init
    - request failure
    - request_success
    - reset_stats
    - user_error
    - report_to_master, etc..
    - How to fire the events?
        - from locust import events.
        - Use the decorator_
        - e.g@events.spawning_complete.add_listener
        - Recommended to add **kwargs(key word arguments)
        - eg; @events.spawning_complete.add_listener
            def spawn_users(user_count,**kwargs):
            print("Spawned ...",user_count,users.")
- EventHook
    - Fire your own events
    - reverse=True to fire events in the reverse order
    - eg: my_event=EventHook()
            def on_my_event(a,b,**kwargs): (two arguments are mandatory)
                print("Event was fired with arguments:%s,%s" % (a,b))
            my_event.add_listener(on_my_event)
            my_event.fire(a="foo",b="bar")
-----
### Distributed Load Testing
- One master machine and many worker machines
- Master machine -> Worker machines -> Injecting load to App
- All conf will be done in master machine
- Master - Worker setup:
    - master.conf
        - [master conf]
        - master=true
        - expect-workers=2
        - [runtime settings]
        - host=https://petstore.octoperf.com
        - users=3
        - spawn-rate=1
        - locustfile=Distributed Load Testing\petstore.py
        - run-time=60s
        - headless=true
        - only-summary=true
    - worker.cong
        - [worker conf]
        - worker=true
        - locustfile=Distributed Load Testing\petstore.py
        - master-host=XXX.XXX.XXX.XXX
- Running Master - Worker Setup:
    - First run in master machine: locust --config master.conf
    - Message: Waiting for workers to be ready,0 of 1 connected
    - Then run in worker machine: locust --config worker.conf
    - Message: Starting Locust 1.4.3
- Important:
    - Locust scripts must be present in all the master and worker machines
    - number_of_users > number_of_user_classes * number_of_workers
-----
### Running Locust in Docker
- docker run -p 8089:8089 -v $PWD:/mnt/locust -d locustio/locust -f /mnt/locust/locustfile.py
- docker run -v$PWD:/mnt/locust locustio/locust -f /mnt/locust/locustfile.py html /mnt/locust/myrun1.html --headless --only-summary -r1-u1-t 10s
- docker ps
- docker exec -it {container_id}/bin/bash
-----
### Distributed Load Testing in Docker
- We need to docker compose to run and build the images
- We need to defien containers and conf in yml file
- to run: docker compose up
- to stop: ctrl + C
- to delete containers: docker compose rm









 Here's the complete change list — five changes, in order.

1. New: CrossClusterSinkProcessor
java
package org.barcapint.processor;

import org.apache.avro.generic.GenericRecord;
import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.streams.errors.StreamsException;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.barcapint.util.RouteTarget;

import static org.barcapint.util.AppConstants.*;

/**
 * Terminal processor - sends directly to cluster 2 (real output/discarded/DLQ
 * topics) using a plain, separately-managed KafkaProducer, bypassing Streams'
 * .to(...) sink entirely (Streams can only sink to the same cluster it consumes
 * from - see architecture discussion). Blocking/synchronous send is deliberate:
 * Streams only commits the source offset after process() returns, so a failed
 * send here means the record is NOT marked processed and gets redelivered on
 * retry/restart - this is what gives us at-least-once safety across the
 * cluster boundary. This write is NOT covered by processing.guarantee=exactly_once_v2
 * (that only ever protects the consume->enrich path on cluster 1).
 */
public class CrossClusterSinkProcessor implements Processor<String, GenericRecord, Void, Void> {

    private final Producer<String, GenericRecord> cluster2Producer;
    private final RouteTarget fixedTarget; // null if target should come from a wrapping call site instead

    public CrossClusterSinkProcessor(Producer<String, GenericRecord> cluster2Producer, RouteTarget fixedTarget) {
        this.cluster2Producer = cluster2Producer;
        this.fixedTarget = fixedTarget;
    }

    @Override
    public void init(ProcessorContext<Void, Void> context) {
        // no-op - this is a terminal processor, nothing to forward downstream
    }

    @Override
    public void process(Record<String, GenericRecord> record) {
        String targetTopic = resolveTargetTopic(fixedTarget);
        try {
            cluster2Producer.send(new ProducerRecord<>(targetTopic, record.key(), record.value())).get();
        } catch (Exception e) {
            throw new StreamsException("Failed producing to cluster 2 topic " + targetTopic, e);
        }
    }

    private String resolveTargetTopic(RouteTarget target) {
        return switch (target) {
            case OUTPUT -> OUTPUT_TOPIC;
            case DISCARDED -> DISCARDED_TOPIC;
            case DLQ -> DLQ_TOPIC;
        };
    }
}

Since EnrichmentProcessor already resolves RouteTarget dynamically per-record (via ProcessingResult), we need a second variant that reads the target from the record rather than taking a fixed one — for the routed branches after EnrichmentProcessor:

java
package org.barcapint.processor;

import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.avro.generic.GenericRecord;
import org.apache.kafka.streams.errors.StreamsException;
import org.apache.kafka.streams.processor.api.Processor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.barcapint.util.ProcessingResult;
import org.barcapint.util.RouteTarget;

import static org.barcapint.util.AppConstants.*;

/** Same as CrossClusterSinkProcessor, but reads RouteTarget from the record itself. */
public class RoutedCrossClusterSinkProcessor implements Processor<String, ProcessingResult, Void, Void> {

    private final Producer<String, GenericRecord> cluster2Producer;

    public RoutedCrossClusterSinkProcessor(Producer<String, GenericRecord> cluster2Producer) {
        this.cluster2Producer = cluster2Producer;
    }

    @Override
    public void init(ProcessorContext<Void, Void> context) {
    }

    @Override
    public void process(Record<String, ProcessingResult> record) {
        ProcessingResult result = record.value();
        String targetTopic = resolveTargetTopic(result.target());
        try {
            cluster2Producer.send(new ProducerRecord<>(targetTopic, record.key(), result.payload())).get();
        } catch (Exception e) {
            throw new StreamsException("Failed producing to cluster 2 topic " + targetTopic, e);
        }
    }

    private String resolveTargetTopic(RouteTarget target) {
        return switch (target) {
            case OUTPUT -> OUTPUT_TOPIC;
            case DISCARDED -> DISCARDED_TOPIC;
            case DLQ -> DLQ_TOPIC;
        };
    }
}
2. New: Plain cluster-2 producer bean (separate from Streams entirely)
java
package org.barcapint.config;

import org.apache.avro.generic.GenericRecord;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.Producer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Properties;

/**
 * Plain, non-Streams-managed producer for cluster 2 (real output/discarded/DLQ
 * topics). Reuses the same enrichment.producer.* property values you already
 * have - this is just a second client instantiated independently, not part of
 * StreamsConfig. Single shared instance - KafkaProducer is thread-safe.
 */
@Configuration
public class Cluster2ProducerConfiguration {

    @Value("${enrichment.producer.bootstrap-servers}")
    private String bootstrapServers;
    @Value("${enrichment.producer.security-protocol}")
    private String securityProtocol;
    @Value("${enrichment.schema-registry.url}")
    private String schemaRegistryUrl;
    // add ssl.*/sasl.* @Value fields here too, mirroring StreamsPropertiesConfiguration's
    // producer fields, ONLY if/when cluster 2 needs them (currently PLAINTEXT in dev)

    @Bean(destroyMethod = "close")
    public Producer<String, GenericRecord> cluster2Producer() {
        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer");
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, "io.confluent.kafka.serializers.KafkaAvroSerializer");
        props.put("schema.registry.url", schemaRegistryUrl);
        props.put("security.protocol", securityProtocol); // PLAINTEXT in dev; SASL_SSL in higher envs
        // add ssl.*/sasl.* props here once cluster 2 requires them in higher envs
        return new KafkaProducer<>(props);
    }
}
3. Update StreamsTopologyConfiguration — replace all .to(...) calls with .process(...)
java
mapped.split(Named.as("branches"))
    .branch((k, v) -> v.isNotRestricted() == IsNotRestricted.FALSE,
        Branched.withConsumer(ks -> ks
                .mapValues(OmniPaymentMap::omniPayment)
                .process(() -> new CrossClusterSinkProcessor(cluster2Producer, RouteTarget.DISCARDED),
                        Named.as("early-discard-sink"))))
    .defaultBranch(Branched.withConsumer(ks -> {
        KStream<String, ProcessingResult> processed = ks.process(processorSupplier, Named.as("enrichment-processor"), ENRICHMENT_STORE_NAME);

        processed.process(() -> new RoutedCrossClusterSinkProcessor(cluster2Producer), Named.as("routed-sink"));
        // no further .split()/.to() needed - the single processor handles all 3 targets internally
    }));

This replaces the old second .split()/.branch()/.to() block entirely — one .process() call now handles output/discarded/DLQ routing internally based on ProcessingResult.target().

New field needed in the class: @Autowired private Producer<String, GenericRecord> cluster2Producer; (injects the bean from step 2).

Remove: the GenericAvroSerde finalEventSerde = registryBackedSerde(); and all Produced.with(Serdes.String(), finalEventSerde) usage — no longer needed since nothing goes through Streams' own .to(...) anymore. (Keep registryBackedSerde() only if you still use it elsewhere, e.g. default.value.serde.)

4. StreamsPropertiesConfiguration — no changes strictly required

producer.* properties can stay as-is (harmless, unused unless changelog logging gets re-enabled later) or be removed for clarity now that Streams' own producer never writes anywhere. I'd leave them — least disruptive, and useful again if the changelog topic gets sorted out (pending item #1).

5. ACL implications — simpler now, worth relaying to platform team
Cluster 1: only needs input-topic Read, consumer-group Read, changelog (currently bypassed) — no more Write needed on cluster 1 for output/discarded/DLQ, since Streams never sinks there anymore.
Cluster 2: needs Write+Describe on real output/discarded/DLQ topics, for whichever identity cluster2Producer authenticates as (currently anonymous/PLAINTEXT in dev, per what we confirmed already works).

This should meaningfully reduce the ACL back-and-forth going forward, since cluster 1 and cluster 2 responsibilities are now cleanly separated by which client is doing the talking.
