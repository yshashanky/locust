# Kafka Streams Migration — XML Transaction Processing with T1 State

## 1. Objective

The current application:

```text
Kafka input topic
    ↓
existing async processing
    ↓
XML processing / transformation
    ↓
GenericRecord
    ↓
KafkaTemplate<String, GenericRecord>
    ↓
restricted / targeted output topic
```

The required change is to introduce **Kafka Streams** so that T1 data can be retained and used when processing later events.

The input events are **XML**, not JSON.

The transaction sequence is logically:

```text
T1 = submit
T2 = subsequent event
T3 = subsequent event
T4 = subsequent event
...
final event = finished
```

All events have the same transaction ID:

```text
Kafka transaction.transaction_id
```

The Kafka record key is **not** the transaction ID.

T1 normally arrives first, but a later event can very rarely arrive before T1.

---

# 2. Target architecture

```text
                         INPUT TOPIC
                      String / String
                            │
                            ▼
              TransactionKafkaStreamsTopology
                            │
                            ▼
                 XML event / transaction ID
                            │
                    extract transaction_id
                            │
                            ▼
                 Re-key using transaction_id
                            │
                            ▼
                      Repartition
                            │
                            ▼
                 Kafka Streams State Store
                    transaction_id → T1
                            │
              ┌─────────────┴──────────────┐
              │                            │
             T1                         T2/T3/T4...
          action=submit                       │
              │                               │
              ▼                               ▼
       Store T1 information            Lookup T1 state
                                              │
                                              ▼
                                   Existing processing /
                                   enrichment logic
                                              │
                                              ▼
                                   Existing XML → Avro
                                              │
                                              ▼
                                  Existing SchemaProvider
                                              │
                                              ▼
                                         GenericRecord
                                              │
                                              ▼
                                      Kafka Streams output
                                              │
                                              ▼
                              RESTRICTED / TARGETED TOPIC
                                    String / GenericRecord

final event = finished
        │
        ├── lookup T1
        ├── process/enrich
        ├── publish final output
        └── delete transaction state
```

The important point is:

**Kafka Streams is being introduced to solve durable transaction state management. It is not replacing your existing XML/Avro business transformation.**

---

# 3. Existing types

These are the confirmed Kafka types:

| Flow | Key | Value |
|---|---|---|
| Input topic | `String` | `String` |
| Output / restricted / targeted topic | `String` | `GenericRecord` |
| DLQ | `String` | `String` |

Therefore:

```java
KStream<String, String>
```

is the input stream.

The output eventually becomes:

```java
KStream<String, GenericRecord>
```

The DLQ remains:

```java
KafkaTemplate<String, String>
```

Your existing output producer remains:

```java
KafkaTemplate<String, GenericRecord>
```

wherever it is still required by existing application flows.

---

# 4. Important: input is XML

Do **not** parse the input as JSON.

The incoming Kafka value is the original XML `String`.

The Streams layer only needs to extract the information required for routing/state management:

```text
transaction.transaction_id
transaction.action
```

The original XML must remain available to the existing processing logic.

The application-specific XML paths/parsing implementation should reuse your existing XML parsing code.

---

# 5. File order

Use this logical implementation order:

```text
1. TransactionKafkaStreamsConfig.java
2. TransactionKafkaStreamsTopology.java
3. TransactionEvent.java
4. TransactionEventParser.java
5. TransactionStateStore.java
6. TransactionStateStoreSerde.java
7. TransactionProcessor.java
8. Existing AsyncProcessingService / business transformation
9. Existing XML → Avro transformation
10. Existing SchemaProvider
11. GenericRecord output
12. Kafka Streams output configuration
```

This is the **logical flow order**.

Spring does not literally execute Java files one after another in this order. Spring creates/configures beans, and then Kafka Streams starts the topology.

---

# 6. File 1 — `TransactionKafkaStreamsConfig.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionKafkaStreamsConfig.java
```

Purpose:

- Kafka Streams application configuration
- Kafka cluster connection
- SSL/SASL configuration
- Schema Registry configuration
- application ID
- Kafka Streams defaults

## Required configuration

The confirmed properties are:

```text
bootstrap.servers
application.id

security.protocol
ssl.endpoint.identification.algorithm

ssl.truststore.location
ssl.truststore.password

ssl.keystore.location
ssl.keystore.password
ssl.key.password

schema.registry.url
auto.register.schemas=false
use.latest.version=false
```

### Example

```java
package <your-package>.kafka;

import io.confluent.kafka.serializers.AbstractKafkaSchemaSerDeConfig;
import org.apache.kafka.clients.CommonClientConfigs;
import org.apache.kafka.common.config.SslConfigs;
import org.apache.kafka.streams.StreamsConfig;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.HashMap;
import java.util.Map;

@Configuration
public class TransactionKafkaStreamsConfig {

    @Value("${spring.kafka.bootstrap-servers}")
    private String bootstrapServers;

    @Value("${spring.kafka.properties.security.protocol}")
    private String securityProtocol;

    @Value("${spring.kafka.properties.ssl.endpoint.identification.algorithm}")
    private String endpointIdentificationAlgorithm;

    @Value("${spring.kafka.properties.ssl.truststore.location}")
    private String truststoreLocation;

    @Value("${spring.kafka.properties.ssl.truststore.password}")
    private String truststorePassword;

    @Value("${spring.kafka.properties.ssl.keystore.location}")
    private String keystoreLocation;

    @Value("${spring.kafka.properties.ssl.keystore.password}")
    private String keystorePassword;

    @Value("${spring.kafka.properties.ssl.key.password}")
    private String keyPassword;

    @Value("${spring.kafka.properties.schema.registry.url}")
    private String schemaRegistryUrl;

    @Bean(name = "transactionKafkaStreamsProperties")
    public Map<String, Object> transactionKafkaStreamsProperties() {

        Map<String, Object> properties = new HashMap<>();

        properties.put(
                StreamsConfig.APPLICATION_ID_CONFIG,
                "payment-transaction-enrichment-${ENVIRONMENT}"
        );

        properties.put(
                CommonClientConfigs.BOOTSTRAP_SERVERS_CONFIG,
                bootstrapServers
        );

        properties.put(
                CommonClientConfigs.SECURITY_PROTOCOL_CONFIG,
                securityProtocol
        );

        properties.put(
                SslConfigs.SSL_ENDPOINT_IDENTIFICATION_ALGORITHM_CONFIG,
                endpointIdentificationAlgorithm
        );

        properties.put(
                SslConfigs.SSL_TRUSTSTORE_LOCATION_CONFIG,
                truststoreLocation
        );

        properties.put(
                SslConfigs.SSL_TRUSTSTORE_PASSWORD_CONFIG,
                truststorePassword
        );

        properties.put(
                SslConfigs.SSL_KEYSTORE_LOCATION_CONFIG,
                keystoreLocation
        );

        properties.put(
                SslConfigs.SSL_KEYSTORE_PASSWORD_CONFIG,
                keystorePassword
        );

        properties.put(
                SslConfigs.SSL_KEY_PASSWORD_CONFIG,
                keyPassword
        );

        /*
         * Schema Registry configuration is required by the Avro
         * SerDe used when the stream produces GenericRecord.
         */
        properties.put(
                AbstractKafkaSchemaSerDeConfig.SCHEMA_REGISTRY_URL_CONFIG,
                schemaRegistryUrl
        );

        properties.put(
                AbstractKafkaSchemaSerDeConfig.AUTO_REGISTER_SCHEMAS,
                false
        );

        properties.put(
                AbstractKafkaSchemaSerDeConfig.USE_LATEST_VERSION,
                false
        );

        return properties;
    }
}
```

## Important configuration notes

The exact property names in your application may differ.

**TODO — map the `@Value` expressions to the existing property names in your application.properties/yaml.**

Do not create duplicate configuration values if the existing Spring Kafka configuration already exposes them.

Also do not literally use:

```text
payment-transaction-enrichment-${ENVIRONMENT}
```

unless your application already defines `ENVIRONMENT`.

Use a stable environment-specific application ID, for example:

```text
payment-transaction-enrichment-dev
payment-transaction-enrichment-qa
payment-transaction-enrichment-prod
```

Do not generate a random ID at startup.

---

# 7. Properties deliberately NOT copied from the existing DLQ producer

The following are not required just because they exist in the current producer configuration:

```text
acks
retries
max.in.flight.requests.per.connection
retry.backoff.ms
batch.size
linger.ms
compression.type
```

They are producer/client tuning parameters, not GenericRecord serialization configuration.

They can be tuned later for Kafka Streams if performance testing shows a need.

---

# 8. File 2 — `TransactionKafkaStreamsTopology.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionKafkaStreamsTopology.java
```

This is the main topology class.

It is the **logical entry point of the Kafka Streams processing flow**.

Kafka Streams internally creates and manages the Kafka consumer.

You do not manually call:

```java
consumer.poll()
```

## Topology

```java
package <your-package>.kafka;

import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.KStream;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class TransactionKafkaStreamsTopology {

    @Value("${transaction.kafka.input-topic}")
    private String inputTopic;

    @Bean
    public KStream<String, String> transactionStream(
            StreamsBuilder builder,
            TransactionEventParser eventParser,
            TransactionProcessor transactionProcessor) {

        /*
         * INPUT:
         *
         * Kafka key   = String
         * Kafka value = XML String
         */
        KStream<String, String> inputStream =
                builder.stream(
                        inputTopic,
                        Consumed.with(
                                Serdes.String(),
                                Serdes.String()
                        )
                );

        /*
         * Parse only the metadata required to route the event.
         *
         * The original XML remains inside TransactionEvent.
         */
        KStream<String, TransactionEvent> events =
                inputStream.mapValues(
                        eventParser::parse
                );

        /*
         * IMPORTANT:
         *
         * The Kafka record key is NOT transaction_id.
         *
         * Therefore we explicitly re-key using the transaction ID.
         */
        KStream<String, TransactionEvent> transactionKeyedStream =
                events.selectKey(
                        (kafkaRecordKey, event) ->
                                event.getTransactionId()
                );

        /*
         * Repartition guarantees that events having the same
         * transaction ID are processed by the same Kafka Streams
         * task/state-store partition.
         *
         * Kafka Streams creates the required internal repartition
         * topic automatically.
         */
        KStream<String, TransactionEvent> repartitioned =
                transactionKeyedStream.repartition();

        /*
         * Stateful processing.
         *
         * TransactionProcessor is responsible for:
         *
         * T1 / submit:
         *      save T1 state
         *
         * T2/T3/T4/...:
         *      retrieve T1 state
         *
         * finished:
         *      retrieve T1
         *      process
         *      delete state
         */
        return repartitioned.process(
                transactionProcessor
        );
    }
}
```

### Important

The exact `repartition()` configuration should be completed with explicit SerDes/name if required by your Kafka Streams version and topology conventions.

**TODO — configure the repartition SerDes using the actual `TransactionEvent` representation selected below.**

---

# 9. File 3 — `TransactionEvent.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionEvent.java
```

This is **not a replacement for the XML payload**.

It is a small wrapper around the incoming event.

```java
package <your-package>.kafka;

public class TransactionEvent {

    private final String transactionId;
    private final String action;
    private final String xmlPayload;

    public TransactionEvent(
            String transactionId,
            String action,
            String xmlPayload) {

        this.transactionId = transactionId;
        this.action = action;
        this.xmlPayload = xmlPayload;
    }

    public String getTransactionId() {
        return transactionId;
    }

    public String getAction() {
        return action;
    }

    public String getXmlPayload() {
        return xmlPayload;
    }
}
```

Purpose:

```text
transactionId = used as Kafka Streams state key
action        = submit / finished / intermediate action
xmlPayload    = original XML
```

---

# 10. File 4 — `TransactionEventParser.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionEventParser.java
```

This class should reuse your existing XML parsing implementation.

Do not introduce JSON parsing.

```java
package <your-package>.kafka;

import org.springframework.stereotype.Component;

@Component
public class TransactionEventParser {

    public TransactionEvent parse(String xmlPayload) {

        /*
         * TODO — integrate your existing XML parser.
         *
         * Extract:
         *
         * 1. Kafka transaction.transaction_id
         * 2. Kafka transaction.action
         *
         * Do NOT convert the entire XML here.
         *
         * Return the original XML unchanged as xmlPayload.
         */

        String transactionId =
                extractTransactionId(xmlPayload);

        String action =
                extractTransactionAction(xmlPayload);

        return new TransactionEvent(
                transactionId,
                action,
                xmlPayload
        );
    }

    private String extractTransactionId(
            String xmlPayload) {

        /*
         * TODO — replace with your existing XML parsing logic.
         */
        throw new UnsupportedOperationException(
                "Integrate existing transaction_id XML extraction"
        );
    }

    private String extractTransactionAction(
            String xmlPayload) {

        /*
         * TODO — replace with your existing XML parsing logic.
         */
        throw new UnsupportedOperationException(
                "Integrate existing transaction.action XML extraction"
        );
    }
}
```

Do not write a second XML parser if your existing application already has one.

---

# 11. File 5 — `TransactionStateStore.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionStateStore.java
```

For this application, the state store only needs to retain the T1 information required for later processing.

Do **not** create an Avro state model.

Conceptually:

```text
transaction_id → T1 XML
```

The state-store implementation will be registered through the Kafka Streams topology.

The state is durable and managed by Kafka Streams rather than being held in a normal JVM `Map`.

---

# 12. File 6 — `TransactionStateStoreSerde.java`

The state store should not require your output Avro schema.

The internal state can be represented as:

```text
String transactionId
String T1 XML payload
```

For the initial implementation, use a JSON/string-based internal representation only if necessary.

However, because the exact T1 information that must survive is dependent on your existing `AsyncProcessingService`, this part should not be over-designed yet.

**TODO — after mapping the existing XML processing code, select whether the state value should contain:**

```text
A. complete T1 XML
```

or:

```text
B. only the T1 fields required by the enrichment/transformation logic
```

Option B is preferable if the required fields are known because it reduces state size.

---

# 13. File 7 — `TransactionProcessor.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionProcessor.java
```

This is the main stateful processing point.

Conceptually:

```text
T1 / submit
    ↓
save T1 state

T2/T3/T4
    ↓
lookup T1
    ↓
call existing processing
    ↓
produce output

finished
    ↓
lookup T1
    ↓
call existing processing
    ↓
produce output
    ↓
delete state
```

The processor should **not contain the XML → Avro business transformation itself**.

It should call the existing application processing.

```java
package <your-package>.kafka;

import org.springframework.stereotype.Component;

@Component
public class TransactionProcessor {

    /*
     * TODO:
     *
     * Wire the Kafka Streams state store here.
     *
     * Also wire the existing business-processing service.
     */

    public TransactionEvent process(
            TransactionEvent event) {

        String transactionId =
                event.getTransactionId();

        String action =
                event.getAction();

        if ("submit".equalsIgnoreCase(action)) {

            /*
             * T1:
             *
             * Save the T1 information into the state store.
             *
             * TODO:
             * Implement stateStore.put(transactionId, T1 data)
             */

            return event;
        }

        /*
         * T2/T3/T4/final:
         *
         * TODO:
         *
         * 1. stateStore.get(transactionId)
         * 2. If T1 exists, pass:
         *
         *      current XML
         *      +
         *      T1 data
         *
         *    to existing processing.
         *
         * 3. If action == finished:
         *      stateStore.delete(transactionId)
         */

        return event;
    }
}
```

This is deliberately the integration boundary for your existing code.

The actual implementation should be completed after mapping the current `AsyncProcessingService`.

---

# 14. Existing `AsyncProcessingService`

Do **not delete this class blindly.**

The migration should extract/reuse its existing business logic.

Current conceptual flow:

```text
Kafka message
    ↓
AsyncProcessingService
    ↓
XML parsing
    ↓
business transformation
    ↓
XML → Avro
    ↓
GenericRecord
    ↓
KafkaTemplate
```

New flow:

```text
Kafka message
    ↓
Kafka Streams
    ↓
transaction state lookup
    ↓
T1 + current XML
    ↓
existing business transformation
    ↓
XML → Avro
    ↓
GenericRecord
    ↓
Kafka Streams output
```

The business logic should remain the same unless there is a specific reason to change it.

---

# 15. Existing XML → Avro transformer

Keep the existing implementation.

It should continue to be responsible for converting the processed/enriched XML into the `GenericRecord`.

Conceptually:

```java
GenericRecord output =
        existingXmlToAvroTransformer.transform(
                processedXml
        );
```

**TODO — replace the method name with your actual transformer method.**

Do not implement another XML → Avro conversion layer.

---

# 16. Existing `SchemaProvider`

Keep your existing SchemaProvider.

You already have a component that obtains the schema from Schema Registry.

Therefore:

```text
Do NOT create a local copy of the Avro output schema.
Do NOT create a new schema loader.
Do NOT hard-code the Avro schema.
```

Use:

```text
Existing SchemaProvider
        ↓
Schema Registry
        ↓
Schema
        ↓
Existing XML → Avro conversion
        ↓
GenericRecord
```

**TODO — integrate the actual SchemaProvider method from the current application.**

---

# 17. GenericRecord serialization

Your existing producer configuration already uses:

```text
key.serializer   = StringSerializer
value.serializer = KafkaAvroSerializer
```

There is no need to manually serialize the `GenericRecord`.

For Kafka Streams output, configure the corresponding Confluent Avro SerDe using the same Schema Registry configuration.

The application should not contain code such as:

```java
record.toBytes()
```

or:

```java
serializer.serialize(...)
```

The Kafka client/Streams layer handles it.

---

# 18. State store versus output Avro schema

These are separate.

### Output

```text
GenericRecord
   ↓
KafkaAvroSerializer
   ↓
Schema Registry
```

### State

```text
transaction_id
      ↓
Kafka Streams state store
      ↓
T1 information
```

The state store does **not** need to use your output topic's Avro schema.

---

# 19. Why transaction ID must be used as the Streams key

Your Kafka record key is not the transaction ID.

Therefore this is required:

```java
events.selectKey(
    (recordKey, event) ->
        event.getTransactionId()
);
```

This is critical.

Kafka Streams state stores are partitioned.

Once the stream is keyed by:

```text
transaction_id
```

all events for:

```text
TX123
```

are routed to the same partition/task.

Therefore:

```text
T1 TX123
T2 TX123
T3 TX123
T4 TX123
finished TX123
```

can all access the same state entry.

---

# 20. Do not use one JVM-wide global store

Do not implement:

```java
static Map<String, String> state;
```

or:

```java
ConcurrentHashMap<String, String>
```

for this.

That would create:

- JVM memory growth
- restart loss
- multi-instance consistency problems
- partition ownership problems
- no durable recovery

Kafka Streams state stores are the appropriate mechanism.

---

# 21. State-store retention

The normal lifecycle is:

```text
T1
 ↓
state stored

T2/T3/T4...
 ↓
state remains

finished
 ↓
final processing
 ↓
state deleted
```

You indicated that the business has not yet confirmed the maximum time.

For now the expected business retention is approximately:

```text
90 days
```

This should be treated as a configurable safety/expiry boundary rather than keeping the state in JVM memory for 90 days.

**TODO — confirm the exact business retention period before final production configuration.**

---

# 22. Out-of-order T2/T3/T4 before T1

Normally:

```text
T1 → T2 → T3 → T4
```

is guaranteed by the application flow.

But you indicated that T2/T3/T4 can very rarely arrive before T1.

Do not:

```java
Thread.sleep(...)
```

Do not retry with an in-memory loop.

The production solution should use durable pending-event handling.

**TODO — implement the agreed strategy for the rare `T2/T3/T4-before-T1` scenario after the primary T1-first flow is integrated.**

---

# 23. Final event

The terminal event is:

```text
transaction.action = finished
```

When it arrives:

```text
lookup T1
    ↓
run existing processing
    ↓
publish final GenericRecord
    ↓
delete state-store entry
```

There can be multiple events before `finished`.

---

# 24. Expected throughput

Peak input:

```text
34,000 messages/hour
```

Approximately:

```text
9.4 messages/second
```

with approximately:

```text
10,000 simultaneous active transactions
```

The state store should therefore be designed around **active transaction count and T1 state size**, not merely messages/second.

The earlier stated T1 payload size is approximately:

```text
10–12 KB
```

Do not keep all T1 records in a JVM collection.

Kafka Streams persistent state storage is used instead.

---

# 25. Kafka partitions

The number of partitions affects:

- parallelism
- which Streams task owns a transaction
- state-store distribution
- throughput
- number of active processing tasks

The important invariant is:

```text
transaction_id
      ↓
same partition
      ↓
same state-store partition
```

The original Kafka record key does not need to be the transaction ID.

The topology explicitly re-keys using `transaction_id`.

---

# 26. No new business Kafka topic required

You do not need to create a manually managed business topic just to hold T1 state.

Kafka Streams will automatically create internal topics required for:

- repartitioning
- state-store changelog/recovery

These are Kafka Streams internal topics.

Your business flow remains:

```text
existing input topic
        ↓
Kafka Streams
        ↓
existing output topic
```

---

# 27. Existing DLQ

Your existing DLQ remains:

```text
String / String
```

and can continue using:

```java
KafkaTemplate<String, String>
```

Do not change it to `GenericRecord` merely because the main output is Avro.

---

# 28. Existing Async configuration

Your existing async executor properties such as:

```text
max pool size
queue capacity
thread name prefix
pool size
```

were designed for the old asynchronous processing model.

Do not automatically copy them into Kafka Streams.

Kafka Streams has its own processing/thread/task model.

The existing business logic can be reused, but the Kafka Streams execution model replaces the need to make the Kafka consumption itself `@Async`.

**TODO — determine which existing async methods are pure business logic and which exist only for asynchronous execution.**

Keep the business logic.

Remove/replace only the asynchronous execution wrapper where appropriate.

---

# 29. What should NOT be rewritten

The migration should not unnecessarily replace:

```text
XML parser
XML transformer
XML → Avro transformer
SchemaProvider
existing Avro schema
existing business transformation
DLQ producer
existing Kafka producer configuration
```

The new Kafka Streams layer is primarily responsible for:

```text
consume
→ extract transaction ID
→ re-key
→ repartition
→ maintain T1 state
→ retrieve T1
→ invoke existing processing
→ output
→ clean up state
```

---

# 30. Final flow

The complete target flow is:

```text
APPLICATION START
       │
       ▼
TransactionKafkaStreamsConfig
       │
       ├── bootstrap servers
       ├── application.id
       ├── SSL/SASL
       └── Schema Registry
       │
       ▼
Kafka Streams starts topology
       │
       ▼
TransactionKafkaStreamsTopology
       │
       ▼
INPUT TOPIC
String / String
       │
       ▼
XML String
       │
       ▼
TransactionEventParser
       │
       ├── transaction_id
       ├── transaction.action
       └── original XML
       │
       ▼
selectKey(transaction_id)
       │
       ▼
Kafka Streams repartition
       │
       ▼
TransactionProcessor
       │
       ├── submit
       │      ↓
       │   save T1 state
       │
       └── subsequent event
              ↓
           lookup T1
              ↓
       existing application processing
              ↓
       XML → Avro transformer
              ↓
       SchemaProvider
              ↓
       GenericRecord
              ↓
       Kafka Streams output
              ↓
       OUTPUT TOPIC
       String / GenericRecord
```

For:

```text
action = finished
```

the same flow is followed, then:

```text
stateStore.delete(transactionId)
```

---

# 31. TODO list before production

The following are the only areas intentionally left dependent on your existing code:

1. **XML transaction ID extraction**
   - Use the existing XML parser.
   - Extract `Kafka transaction.transaction_id`.

2. **XML action extraction**
   - `submit` identifies T1.
   - `finished` identifies terminal event.

3. **Existing AsyncProcessingService**
   - Identify business logic that should be reused.
   - Separate it from async execution infrastructure.

4. **Existing XML → Avro transformer**
   - Reuse it.

5. **Existing SchemaProvider**
   - Reuse it.

6. **GenericRecord creation**
   - Reuse the existing implementation.

7. **TransactionState value**
   - Decide whether to retain complete T1 XML or only required T1 fields.
   - Prefer only required fields when the enrichment rules are known.

8. **T2/T3/T4 before T1**
   - Implement durable pending-event handling.

9. **Retention**
   - Confirm the final business retention period.
   - Current working assumption: 90 days.

10. **Kafka Streams partition/repartition configuration**
    - Confirm the input topic partition count.
    - Configure the topology appropriately after that is known.

11. **Schema Registry authentication**
    - If the existing Schema Registry requires additional authentication properties beyond the URL, reuse those existing properties in the Streams Avro SerDe configuration.

---

# 32. Key design rule

The implementation should **add Kafka Streams state management around the existing application**, not replace the existing application's XML/Avro processing.

The target is:

```text
Existing business logic
        +
Kafka Streams state management
        =
final implementation
```

not:

```text
Existing application
        ↓
throw away
        ↓
new generic JSON implementation
```
