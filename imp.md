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

The updated flow is:

```text
                         INPUT TOPIC
                      String / String
                            │
                            ▼
              TransactionKafkaStreamsTopology
                            │
                            ▼
                       XML payload
                            │
                            ▼
                 Existing XML → Avro
                     transformation
                            │
                            ▼
                    Existing SchemaProvider
                            │
                            ▼
                       GenericRecord
                            │
                            ▼
                 [NEW EXTERNAL LOGIC]
                            │
                            ▼
                 Extract transaction_id
                 + transaction.action
                            │
                            ▼
                 Re-key using transaction_id
                            │
                            ▼
                      Repartition
                            │
                            ▼
                 Kafka Streams State Store
                            │
              ┌─────────────┴──────────────┐
              │                            │
       action = submit              action != submit
              │                            │
              ▼                            ▼
       Store T1 GenericRecord        Lookup T1 GenericRecord
                                           │
                                           ▼
                                  Existing/new enrichment
                                           │
                                           ▼
                                  Updated GenericRecord
                                           │
                                           ▼
                                  Output / targeted topic
```

### Important design decision

The XML → Avro transformation happens **before the state store**.

The state store therefore stores the already-transformed `GenericRecord` for T1 rather than raw XML.

The processing order is:

```text
XML
 ↓
XML → Avro
 ↓
SchemaProvider
 ↓
GenericRecord
 ↓
External logic
 ↓
Extract transaction ID/action
 ↓
Re-key
 ↓
Repartition
 ↓
State Store
 ↓
T1 store OR later-event lookup
 ↓
Enrichment/update
 ↓
Output
```

This preserves the existing XML/Avro transformation while allowing the new stateful logic to operate on `GenericRecord`.

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

This is the main Kafka Streams topology.

The input is:

```text
String key
String XML value
```

The XML is immediately passed to the existing XML → Avro transformation.

The topology then works with:

```text
GenericRecord
```

### Updated topology flow

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
    public KStream<String, GenericRecord> transactionStream(
            StreamsBuilder builder,
            ExistingXmlToAvroTransformer xmlToAvroTransformer,
            TransactionEventParser eventParser,
            TransactionProcessor transactionProcessor) {

        /*
         * STEP 1
         *
         * Read the existing input topic.
         *
         * Kafka record:
         *   key   = String
         *   value = XML String
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
         * STEP 2
         *
         * Existing XML -> Avro conversion.
         *
         * This must reuse your existing application logic.
         *
         * TODO:
         * Replace ExistingXmlToAvroTransformer with the actual
         * transformer/service from your application.
         */
        KStream<String, GenericRecord> avroStream =
                inputStream.mapValues(
                        xmlToAvroTransformer::transform
                );

        /*
         * STEP 3
         *
         * Any new logic that you want to execute immediately
         * after GenericRecord creation can be added here.
         *
         * TODO:
         * Add your new external logic here if it does not require
         * previously stored T1 state.
         */

        /*
         * STEP 4
         *
         * Extract:
         *   transaction.transaction_id
         *   transaction.action
         *
         * from the GenericRecord.
         */
        KStream<String, TransactionEvent> eventStream =
                avroStream.mapValues(
                        eventParser::parse
                );

        /*
         * STEP 5
         *
         * The original Kafka record key is NOT the transaction ID.
         *
         * Explicitly use transaction_id as the new Kafka Streams key.
         */
        KStream<String, TransactionEvent> transactionKeyedStream =
                eventStream.selectKey(
                        (originalKey, event) ->
                                event.getTransactionId()
                );

        /*
         * STEP 6
         *
         * Repartition by transaction_id.
         *
         * This guarantees that events for the same transaction
         * are routed to the same state-store partition.
         *
         * TODO:
         * Configure explicit repartition name/SerDes if required
         * by the final topology.
         */
        KStream<String, TransactionEvent> repartitionedStream =
                transactionKeyedStream.repartition();

        /*
         * STEP 7
         *
         * Stateful processing:
         *
         * T1 / submit:
         *      store T1 GenericRecord
         *
         * T2/T3/T4/...:
         *      lookup T1 GenericRecord
         *      enrich/update current GenericRecord
         *
         * finished:
         *      process final event
         *      delete state
         *
         * TODO:
         * Finalize the Processor API implementation and state-store
         * registration once the exact GenericRecord state schema
         * and existing enrichment method are integrated.
         */
        return transactionProcessor.process(
                repartitionedStream
        );
    }
}
```

**Important:** the above is the topology structure. The exact method signatures of your existing XML → Avro transformer and SchemaProvider must replace the placeholders.

# 9. File 3 — `TransactionEvent.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionEvent.java
```

This class now represents the already-transformed event.

It should not contain the XML payload as the primary processing object.

```java
package <your-package>.kafka;

import org.apache.avro.generic.GenericRecord;

public class TransactionEvent {

    private final String transactionId;
    private final String action;
    private final GenericRecord record;

    public TransactionEvent(
            String transactionId,
            String action,
            GenericRecord record) {

        this.transactionId = transactionId;
        this.action = action;
        this.record = record;
    }

    public String getTransactionId() {
        return transactionId;
    }

    public String getAction() {
        return action;
    }

    public GenericRecord getRecord() {
        return record;
    }
}
```

The important distinction is:

```text
XML
 ↓
existing transformation
 ↓
GenericRecord
 ↓
TransactionEvent
```

The state store will retain the T1 `GenericRecord`.

# 10. File 4 — `TransactionEventParser.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionEventParser.java
```

This parser receives a `GenericRecord`, not XML.

Its only responsibility is extracting the fields required by Kafka Streams:

```text
transaction.transaction_id
transaction.action
```

```java
package <your-package>.kafka;

import org.apache.avro.generic.GenericRecord;
import org.springframework.stereotype.Component;

@Component
public class TransactionEventParser {

    public TransactionEvent parse(GenericRecord record) {

        String transactionId =
                extractTransactionId(record);

        String action =
                extractTransactionAction(record);

        return new TransactionEvent(
                transactionId,
                action,
                record
        );
    }

    private String extractTransactionId(
            GenericRecord record) {

        /*
         * TODO:
         *
         * Replace this with the exact GenericRecord field path
         * used by your existing Avro schema.
         *
         * Example only:
         *
         * GenericRecord transaction =
         *         (GenericRecord) record.get("transaction");
         *
         * return transaction.get("transaction_id").toString();
         */
        throw new UnsupportedOperationException(
                "Integrate actual transaction_id extraction"
        );
    }

    private String extractTransactionAction(
            GenericRecord record) {

        /*
         * TODO:
         *
         * Replace this with the exact GenericRecord field path
         * used by your existing Avro schema.
         */
        throw new UnsupportedOperationException(
                "Integrate actual transaction.action extraction"
        );
    }
}
```

Do not guess the Avro field path. Use the schema already returned by your existing SchemaProvider.

# 11. File 5 — `TransactionStateStore.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionStateStore.java
```

The state store represents:

```text
transaction_id → T1 GenericRecord
```

The value is therefore the already-transformed T1 `GenericRecord`.

Do not use a JVM `Map`.

The actual Kafka Streams store should be a persistent state store registered with the topology.

Recommended conceptual API:

```java
public interface TransactionStateStore {

    void put(
            String transactionId,
            GenericRecord t1Record
    );

    GenericRecord get(
            String transactionId
    );

    void delete(
            String transactionId
    );
}
```

**TODO — implement this interface using a Kafka Streams `KeyValueStore<String, GenericRecord>` registered with the topology.**

The store must be backed by Kafka Streams' changelog mechanism so it can recover after application restart.

# 12. File 6 — `TransactionStateStoreSerde.java`

Because the state value is now:

```text
GenericRecord
```

the state store cannot use:

```java
Serdes.String()
```

for the value.

The state store needs a `Serde<GenericRecord>`.

Use the Confluent Generic Avro SerDe with the existing Schema Registry configuration.

Conceptually:

```java
GenericAvroSerde genericAvroSerde = new GenericAvroSerde();

Map<String, Object> serdeConfig = new HashMap<>();

serdeConfig.put(
        AbstractKafkaSchemaSerDeConfig.SCHEMA_REGISTRY_URL_CONFIG,
        schemaRegistryUrl
);

serdeConfig.put(
        AbstractKafkaSchemaSerDeConfig.AUTO_REGISTER_SCHEMAS,
        false
);

serdeConfig.put(
        AbstractKafkaSchemaSerDeConfig.USE_LATEST_VERSION,
        false
);

genericAvroSerde.configure(
        serdeConfig,
        false
);
```

**TODO — use the existing application Schema Registry/security properties rather than duplicating configuration.**

**TODO — verify that the state-store GenericRecord schema is compatible with the records being stored.**

Do not create a local Avro schema merely for this state store.

# 13. File 7 — `TransactionProcessor.java`

Path:

```text
src/main/java/<your-package>/kafka/TransactionProcessor.java
```

This is where the stateful business flow starts.

Conceptually:

```text
GenericRecord
    ↓
transaction_id + action
    ↓
repartitioned by transaction_id
    ↓
TransactionProcessor
    │
    ├── submit
    │      ↓
    │   store current GenericRecord as T1
    │
    └── other event
           ↓
        lookup T1 GenericRecord
           ↓
        enrichment / update
           ↓
        output GenericRecord
```

For `finished`:

```text
lookup T1
   ↓
process final event
   ↓
publish
   ↓
delete transaction state
```

The processor should not recreate XML → Avro processing.

It receives a `GenericRecord` that has already gone through the existing transformation.

**TODO — implement this using the Kafka Streams Processor API / state store access.**

A high-level processing contract is:

```java
public GenericRecord process(
        String transactionId,
        String action,
        GenericRecord currentRecord,
        GenericRecord t1Record) {

    if ("submit".equalsIgnoreCase(action)) {

        // TODO:
        // Store currentRecord as T1 state.

        return currentRecord;
    }

    // TODO:
    // Retrieve T1 state.
    //
    // Apply your enrichment/update logic to currentRecord
    // using t1Record.
    //
    // Return the final GenericRecord to publish.

    return currentRecord;
}
```

Do not use this method signature directly if the Processor API requires a different callback shape. It describes the business contract only.

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

The final target flow is:

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
Existing XML → Avro transformer
       │
       ▼
Existing SchemaProvider
       │
       ▼
GenericRecord
       │
       ▼
[NEW EXTERNAL LOGIC — if applicable]
       │
       ▼
Extract transaction_id + transaction.action
       │
       ▼
selectKey(transaction_id)
       │
       ▼
Repartition
       │
       ▼
Kafka Streams State Store
       │
       ├── submit
       │      ↓
       │   store T1 GenericRecord
       │
       └── T2/T3/T4/...
              ↓
           lookup T1 GenericRecord
              ↓
           enrichment/update
              ↓
           GenericRecord
              ↓
           output topic
              │
              ▼
       String / GenericRecord
```

For:

```text
transaction.action = finished
```

the flow is:

```text
finished event
    ↓
GenericRecord
    ↓
transaction_id
    ↓
state-store lookup
    ↓
existing/new enrichment
    ↓
output GenericRecord
    ↓
publish
    ↓
delete transaction state
```

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

The implementation should add Kafka Streams state management around the existing application.

The new target is:

```text
XML
 ↓
existing XML → Avro
 ↓
existing SchemaProvider
 ↓
GenericRecord
 ↓
new external logic (if required)
 ↓
transaction_id extraction
 ↓
re-key
 ↓
repartition
 ↓
state store
 ↓
T1 store / T1 lookup
 ↓
enrichment/update
 ↓
GenericRecord output
```

The existing XML/Avro processing is **not being replaced**.
