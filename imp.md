# Kafka Streams Transaction Enrichment — Final Production Integration Guide

## 1. Final assumptions from our discussion

This document is the corrected version based on the latest information.

### Application

- Spring Boot: **3.5.13**
- Kafka client: **3.9.2**
- Kafka Streams: use the version compatible with the application's managed Kafka/Spring Kafka dependencies
- Existing application already uses Kafka
- Existing application currently has `@KafkaListener` + `@Async`
- We are migrating this **specific transaction flow** to Kafka Streams
- Existing unrelated `@Async` functionality can remain unchanged

### Input/output data

The main restricted/targeted Kafka producer is:

```java
KafkaTemplate<String, GenericRecord>
```

The DLQ producer is:

```java
KafkaTemplate<String, String>
```

Therefore, the main stream should remain:

```java
KStream<String, GenericRecord>
```

**Do not convert the main implementation to `Map<String,Object>` merely because the business code uses `put()` operations.**

Your existing `GenericRecord` remains the business payload.

### Transaction relationship

The transaction ID is:

```text
KafkaTransaction.transaction_id
```

It is **not** the Kafka record key.

Events are related using this payload field.

Example:

```text
T1 → transaction_id = ABC123 → action = submit
T2 → transaction_id = ABC123
T3 → transaction_id = ABC123
T4 → transaction_id = ABC123 → action = finished
```

### Event behavior

- T1 has `action = submit`
- T1 normally arrives first
- T2/T3/T4 can very rarely arrive before T1
- There can be more than four events
- There is one terminal event
- Terminal event has `action = finished`
- T2/T3/T4/etc. must all be enriched using T1
- T1 itself is the source of the complete data
- T1 can remain relevant for days/weeks
- 90 days is currently a provisional business retention boundary
- Peak traffic: ~34,000 messages/hour ≈ **9.44 messages/sec**
- Around 10,000 simultaneous active transactions
- T1 payload is approximately 10–12 KB
- Kafka listener concurrency in the old implementation is currently 1

### External storage

No:

- Redis
- database
- external cache

The durable state should be Kafka Streams' local state store backed by Kafka changelogging.

---

# 2. Final architecture

The old flow is approximately:

```text
Input Kafka Topic
      ↓
KafkaListener
      ↓
@Async
      ↓
AsyncProcessingService
      ↓
Business transformation
      ↓
KafkaTemplate<String, GenericRecord>
      ↓
Output Kafka Topic
```

The new flow becomes:

```text
Input Kafka Topic
      ↓
Kafka Streams
      ↓
GenericRecord
      ↓
Extract transaction_id from payload
      ↓
selectKey(transaction_id)
      ↓
Kafka internal repartition topic
      ↓
Stateful Processor
      │
      ├── submit
      │      ↓
      │   save T1
      │
      ├── T2/T3/T4/...
      │      ↓
      │   lookup T1
      │      ↓
      │   enrich current GenericRecord
      │
      └── finished
             ↓
          lookup T1
             ↓
          enrich
             ↓
          delete state
      ↓
Existing transformation/business logic
      ↓
KStream<String, GenericRecord>
      ↓
Output Kafka Topic
```

---

# 3. Why Kafka Streams is the right solution

The key requirement is not simply asynchronous processing.

It is:

> Keep T1 state available for an unknown amount of time and use it to enrich every later event belonging to the same transaction.

Kafka Streams provides:

- persistent local state
- Kafka-backed changelog
- automatic state recovery
- partition-local processing
- state lookup by transaction ID
- re-keying/repartitioning
- controlled stream processing
- no Redis/database requirement

At ~9.4 messages/sec peak, this workload is modest for Kafka Streams.

---

# 4. What happens to the existing classes

## 4.1 `KafkaConsumerService`

### Current

Something similar to:

```java
@KafkaListener(
    topics = "${...}",
    concurrency = "1"
)
public void consume(...) {
    asyncProcessingService.process(...);
}
```

### Final

For this particular transaction topic:

```diff
- @KafkaListener(...)
- public void consume(...) {
-     asyncProcessingService.process(...);
- }

+ // Kafka Streams now owns consumption of this topic.
```

Do not leave both the old listener and Kafka Streams consuming the same input flow unless that is explicitly intended.

Otherwise the two consumers will belong to different consumer groups and both may process the same events.

### Keep the class if

Other topics/features still use it.

---

# 5. `AsyncProcessingService`

Do **not** immediately delete it.

Separate its responsibilities into:

### Infrastructure responsibilities — remove from this flow

```text
@Async
CompletableFuture
executor/thread-pool handling
acknowledgement
KafkaTemplate send
```

### Business responsibilities — retain/reuse

```text
transformation
field mapping
business rules
output construction
existing enrichment logic
```

The business portion should be exposed through a normal synchronous service/adapter.

Example:

```java
@Component
public class ExistingTransformationAdapter {

    public GenericRecord transform(
            GenericRecord enrichedRecord) {

        // Move/reuse the actual business transformation
        // currently present in AsyncProcessingService.

        return enrichedRecord;
    }
}
```

Do not duplicate the business logic.

---

# 6. Existing async configuration

If the application has:

```yaml
async:
  core-pool-size: ...
  max-pool-size: ...
  queue-capacity: ...
  thread-name-prefix: ...
```

do not remove it immediately.

If other application components use it:

```text
KEEP
```

If it is used only by this transaction flow:

```text
REMOVE AFTER MIGRATION
```

It will no longer control Kafka Streams processing.

Do **not** call `@Async` from the Kafka Streams processor.

---

# 7. Recommended package structure

Use your existing root package.

```text
src/main/java/<your-package>/

├── config/
│   ├── KafkaStreamsConfig.java
│   └── TransactionEnrichmentProperties.java
│
├── enrichment/
│   ├── TransactionEnrichmentTopology.java
│   ├── TransactionEnrichmentProcessor.java
│   ├── TransactionEnricher.java
│   ├── TransactionState.java
│   ├── TransactionStateSerde.java
│   ├── TransactionStateStoreNames.java
│   └── MissingTransactionStateException.java
│
├── transformation/
│   └── ExistingTransformationAdapter.java
│
└── existing/
    ├── KafkaConsumerService.java
    └── AsyncProcessingService.java
```

Use your actual package naming.

---

# 8. Dependencies

Add Kafka Streams if it is not already transitively available:

```xml
<dependency>
    <groupId>org.apache.kafka</groupId>
    <artifactId>kafka-streams</artifactId>
</dependency>
```

Keep your existing:

```xml
<dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
</dependency>
```

Do not manually force a Kafka Streams version that conflicts with Spring Boot's dependency management.

---

# 9. Important clarification about serialization

You said that your current business code does not explicitly serialize/deserialize the payload.

That is completely fine.

Your current application likely hides serialization at the Spring Kafka/KafkaTemplate boundary.

Your main producer is:

```java
KafkaTemplate<String, GenericRecord>
```

Therefore the final Kafka Streams flow should be:

```text
Kafka bytes
    ↓
existing/compatible GenericRecord Avro SerDe
    ↓
GenericRecord
    ↓
business processing
    ↓
GenericRecord
    ↓
existing/compatible GenericRecord Avro SerDe
    ↓
Kafka bytes
```

You do **not** need to manually call:

```java
serializer.serialize(...)
deserializer.deserialize(...)
```

inside business code.

However, Kafka Streams itself must have a SerDe because it directly consumes from and produces to Kafka.

---

# 10. Schema Registry

Because your main producer uses:

```java
KafkaTemplate<String, GenericRecord>
```

the existing GenericRecord serializer configuration is important.

Do **not** create a second unrelated Schema Registry setup.

Reuse the existing application configuration if the same Avro/Schema Registry contract applies to this topic.

The important rule is:

```text
Existing GenericRecord serialization configuration
                    ↓
        Kafka Streams boundary
```

The business enrichment code itself does not need to know about Schema Registry.

---

# 11. GenericRecord SerDe — integration point

Create:

```text
src/main/java/<your-package>/config/GenericRecordSerdeProvider.java
```

The exact implementation depends on the serializer already used by your application.

Do **not** invent a new serializer if you already have one.

Conceptually:

```java
@Component
public class GenericRecordSerdeProvider {

    public Serde<GenericRecord> createSerde() {

        /*
         * TODO:
         *
         * Wire the exact GenericRecord Avro SerDe already used
         * by the application's KafkaTemplate<String, GenericRecord>.
         *
         * If your producer currently uses:
         *
         * KafkaAvroSerializer
         *
         * configure the corresponding Kafka Streams SerDe using
         * the same Schema Registry URL and serializer properties.
         */

        throw new UnsupportedOperationException(
                "Wire existing GenericRecord Avro SerDe here"
        );
    }
}
```

### Why this is intentionally an integration point

The exact serializer configuration depends on:

- whether your current producer uses `KafkaAvroSerializer`
- whether Schema Registry is Confluent
- subject naming strategy
- auto-register settings
- authentication
- existing serializer properties
- whether the GenericRecord schema is the same for input and output

Those values should be copied from your actual application configuration rather than guessed.

---

# 12. Transaction state model

Create:

```text
src/main/java/<your-package>/enrichment/TransactionState.java
```

```java
package <your-package>.enrichment;

import org.apache.avro.generic.GenericRecord;

public class TransactionState {

    private String transactionId;

    /*
     * T1 contains the complete data required for subsequent enrichment.
     *
     * Initially this can hold the full T1 GenericRecord.
     *
     * Later, if only a subset is required, replace this with a
     * compact state model to reduce state-store/changelog size.
     */
    private GenericRecord t1Record;

    private long createdAtEpochMs;

    private long lastUpdatedEpochMs;

    public String getTransactionId() {
        return transactionId;
    }

    public void setTransactionId(String transactionId) {
        this.transactionId = transactionId;
    }

    public GenericRecord getT1Record() {
        return t1Record;
    }

    public void setT1Record(GenericRecord t1Record) {
        this.t1Record = t1Record;
    }

    public long getCreatedAtEpochMs() {
        return createdAtEpochMs;
    }

    public void setCreatedAtEpochMs(long createdAtEpochMs) {
        this.createdAtEpochMs = createdAtEpochMs;
    }

    public long getLastUpdatedEpochMs() {
        return lastUpdatedEpochMs;
    }

    public void setLastUpdatedEpochMs(long lastUpdatedEpochMs) {
        this.lastUpdatedEpochMs = lastUpdatedEpochMs;
    }
}
```

---

# 13. State store name

Create:

```text
src/main/java/<your-package>/enrichment/TransactionStateStoreNames.java
```

```java
package <your-package>.enrichment;

public final class TransactionStateStoreNames {

    private TransactionStateStoreNames() {
    }

    public static final String T1_STATE_STORE =
            "transaction-t1-state-store";
}
```

---

# 14. State store serialization

The state store itself needs a SerDe.

This is different from your existing KafkaTemplate producer.

The state is persisted locally and backed up through Kafka's changelog.

For a first implementation:

```text
TransactionState
    ↓
JSON/binary state SerDe
    ↓
RocksDB/local state store
    ↓
Kafka changelog
```

A production implementation should use a deterministic serialization format.

Because `TransactionState` contains `GenericRecord`, the safest final approach is to use a proper binary/Avro representation or a custom serializer that preserves the GenericRecord schema.

Do not blindly use Jackson against arbitrary `GenericRecord`.

Create:

```text
src/main/java/<your-package>/enrichment/TransactionStateSerde.java
```

and wire a proper state representation according to the actual schema.

---

# 15. Enrichment class

Create:

```text
src/main/java/<your-package>/enrichment/TransactionEnricher.java
```

This is intentionally separate because you will provide the actual enrichment rules.

```java
package <your-package>.enrichment;

import org.apache.avro.generic.GenericRecord;
import org.springframework.stereotype.Component;

@Component
public class TransactionEnricher {

    public GenericRecord enrich(
            GenericRecord currentEvent,
            GenericRecord t1Record) {

        /*
         * TODO:
         *
         * Implement your exact T1 → current-event mapping.
         *
         * Example:
         *
         * currentEvent.put(
         *     "customer_id",
         *     t1Record.get("customer_id")
         * );
         *
         * currentEvent.put(
         *     "payment_details",
         *     t1Record.get("payment_details")
         * );
         */

        return currentEvent;
    }
}
```

### Critical rule

T2, T3, T4 and any later event are enriched from:

```text
T1
```

not from:

```text
T1 → T2 → T3
```

The state remains the original T1 source.

---

# 16. Existing transformation adapter

Create:

```text
src/main/java/<your-package>/transformation/ExistingTransformationAdapter.java
```

```java
package <your-package>.transformation;

import org.apache.avro.generic.GenericRecord;
import org.springframework.stereotype.Component;

@Component
public class ExistingTransformationAdapter {

    public GenericRecord transform(
            GenericRecord enrichedRecord) {

        /*
         * TODO:
         *
         * Call/move the business transformation logic currently
         * present in AsyncProcessingService.
         */

        return enrichedRecord;
    }
}
```

---

# 17. Processor

Create:

```text
src/main/java/<your-package>/enrichment/TransactionEnrichmentProcessor.java
```

Conceptually:

```java
package <your-package>.enrichment;

import org.apache.avro.generic.GenericRecord;
import org.apache.kafka.streams.processor.api.ContextualProcessor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.KeyValueStore;

public class TransactionEnrichmentProcessor
        extends ContextualProcessor<
                String,
                GenericRecord,
                String,
                GenericRecord> {

    private final String stateStoreName;
    private final TransactionEnricher enricher;

    private KeyValueStore<String, TransactionState> stateStore;

    public TransactionEnrichmentProcessor(
            String stateStoreName,
            TransactionEnricher enricher) {

        this.stateStoreName = stateStoreName;
        this.enricher = enricher;
    }

    @SuppressWarnings("unchecked")
    @Override
    public void init(
            ProcessorContext<String, GenericRecord> context) {

        super.init(context);

        this.stateStore =
                (KeyValueStore<String, TransactionState>)
                        context.getStateStore(stateStoreName);
    }

    @Override
    public void process(
            Record<String, GenericRecord> record) {

        GenericRecord event = record.value();

        if (event == null) {
            return;
        }

        String transactionId =
                requiredString(
                        event,
                        "transaction_id"
                );

        String action =
                requiredString(
                        event,
                        "action"
                );

        if ("submit".equalsIgnoreCase(action)) {

            saveT1(
                    transactionId,
                    event
            );

            /*
             * T1 can now continue through the existing output
             * transformation path.
             */
            context().forward(record);

            return;
        }

        TransactionState state =
                stateStore.get(transactionId);

        if (state == null) {

            /*
             * DO NOT publish an incomplete event.
             *
             * The production implementation should route this
             * into durable pending-event handling.
             */
            throw new MissingTransactionStateException(
                    transactionId,
                    action
            );
        }

        GenericRecord enriched =
                enricher.enrich(
                        event,
                        state.getT1Record()
                );

        context().forward(
                record.withValue(enriched)
        );

        if ("finished".equalsIgnoreCase(action)) {

            stateStore.delete(transactionId);

        } else {

            state.setLastUpdatedEpochMs(
                    System.currentTimeMillis()
            );

            stateStore.put(
                    transactionId,
                    state
            );
        }
    }

    private void saveT1(
            String transactionId,
            GenericRecord t1) {

        long now =
                System.currentTimeMillis();

        TransactionState state =
                new TransactionState();

        state.setTransactionId(transactionId);
        state.setT1Record(t1);
        state.setCreatedAtEpochMs(now);
        state.setLastUpdatedEpochMs(now);

        stateStore.put(
                transactionId,
                state
        );
    }

    private String requiredString(
            GenericRecord record,
            String field) {

        Object value =
                record.get(field);

        if (value == null) {

            throw new IllegalArgumentException(
                    "Required field '" +
                    field +
                    "' is missing"
            );
        }

        return value.toString();
    }
}
```

---

# 18. Missing T1

Create:

```text
src/main/java/<your-package>/enrichment/MissingTransactionStateException.java
```

```java
package <your-package>.enrichment;

public class MissingTransactionStateException
        extends RuntimeException {

    public MissingTransactionStateException(
            String transactionId,
            String action) {

        super(
                "T1 state not available for transactionId="
                        + transactionId
                        + ", action="
                        + action
        );
    }
}
```

## Important

This exception is **not the final production solution** for the rare:

```text
T2 → T1
```

case.

We must not lose T2.

The final implementation should use durable Kafka-backed pending-event handling.

Do not use:

```java
ConcurrentHashMap
List<GenericRecord>
Thread.sleep()
CompletableFuture.delayedExecutor()
```

for this.

---

# 19. Topology

Create:

```text
src/main/java/<your-package>/enrichment/TransactionEnrichmentTopology.java
```

The topology should conceptually be:

```java
@Configuration
public class TransactionEnrichmentTopology {

    @Bean
    public KStream<String, GenericRecord> transactionStream(
            StreamsBuilder builder,
            GenericRecordSerdeProvider serdeProvider,
            TransactionEnricher enricher,
            ExistingTransformationAdapter transformationAdapter) {

        Serde<GenericRecord> genericRecordSerde =
                serdeProvider.createSerde();

        KStream<String, GenericRecord> source =
                builder.stream(
                        inputTopic,
                        Consumed.with(
                                Serdes.String(),
                                genericRecordSerde
                        )
                );

        KStream<String, GenericRecord> keyed =
                source.selectKey(
                        (oldKey, event) -> {

                            Object id =
                                    event.get("transaction_id");

                            if (id == null) {
                                throw new IllegalArgumentException(
                                        "transaction_id is missing"
                                );
                            }

                            return id.toString();
                        },
                        Named.as("key-by-transaction-id")
                );

        /*
         * Required because transaction_id is not currently
         * the Kafka record key.
         */
        KStream<String, GenericRecord> repartitioned =
                keyed.repartition(
                        Repartitioned.with(
                                Serdes.String(),
                                genericRecordSerde
                        ).withName(
                                "transaction-id-repartition"
                        )
                );

        /*
         * Attach persistent state store.
         */
        // stateStoreBuilder = ...

        KStream<String, GenericRecord> enriched =
                repartitioned.process(
                        () -> new TransactionEnrichmentProcessor(
                                TransactionStateStoreNames
                                        .T1_STATE_STORE,
                                enricher
                        ),
                        Named.as("transaction-enrichment"),
                        stateStoreBuilder
                );

        /*
         * Existing business transformation.
         */
        KStream<String, GenericRecord> transformed =
                enriched.mapValues(
                        transformationAdapter::transform
                );

        transformed.to(
                outputTopic,
                Produced.with(
                        Serdes.String(),
                        genericRecordSerde
                )
        );

        return source;
    }
}
```

### Important

The above is the structural skeleton.

The final implementation must wire the exact `GenericRecord` SerDe and `TransactionState` state-store SerDe from your project.

---

# 20. Critical topology rule

Do not accidentally do:

```text
repartitioned
    ├── processor
    └── output
```

because that would send the un-enriched stream to the output.

The correct flow is:

```text
repartitioned
      ↓
processor
      ↓
enriched
      ↓
existing transformation
      ↓
output
```

---

# 21. Re-keying is mandatory

Because your Kafka record key is **not** the transaction ID:

```java
.selectKey(
    (oldKey, record) ->
        record.get("transaction_id").toString()
)
```

must happen before stateful processing.

Then:

```text
T1 ABC123
T2 ABC123
T3 ABC123
T4 ABC123

       ↓

transaction_id = ABC123
       ↓
same Kafka partition
       ↓
same Kafka Streams task
       ↓
same state store
```

This is what makes the state lookup reliable.

---

# 22. Will we need a new Kafka topic?

### You do not need a new business topic.

Kafka Streams will create internal topics.

At minimum, expect an internal repartition topic:

```text
<application-id>-transaction-id-repartition
```

and a state-store changelog topic similar to:

```text
<application-id>-transaction-t1-state-store-changelog
```

Names depend on topology naming.

These are infrastructure topics, not new business output topics.

Kafka Streams needs permission to create/read/write them.

---

# 23. State store behavior

The state is:

```text
transaction_id → T1
```

Example:

```text
ABC123 → T1
XYZ456 → T1
LMN999 → T1
```

T2:

```text
ABC123
   ↓
lookup
   ↓
T1
   ↓
enrich T2
```

T3:

```text
ABC123
   ↓
lookup
   ↓
T1
   ↓
enrich T3
```

T4/terminal:

```text
ABC123
   ↓
lookup
   ↓
T1
   ↓
enrich T4
   ↓
finished
   ↓
delete ABC123
```

---

# 24. State retention

There are two concepts.

## A. Normal lifecycle cleanup

When:

```text
action = finished
```

delete:

```java
stateStore.delete(transactionId);
```

This should be the normal cleanup path.

## B. Maximum safety lifetime

You currently want approximately:

```text
90 days
```

until business confirms the exact requirement.

Do not treat Kafka topic retention as the only mechanism for deleting state from the local store.

The final implementation should have an explicit policy for stale transactions.

Keep the retention value configurable.

---

# 25. State size and memory

Current estimates:

```text
10,000 active transactions
×
12 KB T1
≈
120 MB raw payload
```

Actual state-store disk consumption will be larger due to:

- RocksDB overhead
- serialization
- indexes
- changelog
- compaction
- metadata

This is still a manageable workload.

### Important

Do not maintain:

```java
Map<String, GenericRecord> allTransactions;
```

on the JVM heap.

Use the Kafka Streams state store.

If enrichment only needs a subset of T1, create a compact state model later.

---

# 26. Performance

Peak:

```text
34,000 messages/hour
≈ 9.44 messages/sec
```

This is modest for Kafka Streams.

The additional operation is:

```text
input
 ↓
re-key
 ↓
repartition topic
 ↓
state store
```

There is some network and Kafka I/O overhead.

But the benefits are:

- durable state
- automatic recovery
- no Redis
- no DB
- no unbounded async queue
- partition-aware processing
- Kafka-native backpressure

For this use case, the trade-off is favorable.

---

# 27. Kafka Streams threads

Your old configuration:

```text
Kafka listener concurrency = 1
```

does not directly map to Kafka Streams.

Start with:

```yaml
num.stream.threads: 1
```

Then tune only if needed.

Kafka Streams parallelism is also limited by the number of input partitions.

Do not increase stream threads blindly.

---

# 28. Recommended Kafka Streams configuration

Example:

```yaml
spring:
  kafka:
    bootstrap-servers: ${KAFKA_BOOTSTRAP_SERVERS}

    streams:
      application-id: ${KAFKA_STREAMS_APPLICATION_ID:<application-name>-transaction-enrichment>

    properties:
      processing.guarantee: at_least_once

      num.stream.threads: 1

      state.dir: ${KAFKA_STREAMS_STATE_DIR:/tmp/<application-name>/kafka-streams}

      replication.factor: 3

      cache.max.bytes.buffering: 10485760

      compression.type: lz4

      auto.offset.reset: earliest

transaction-enrichment:
  input-topic: ${TRANSACTION_INPUT_TOPIC}
  output-topic: ${TRANSACTION_OUTPUT_TOPIC}

  state-store-name: transaction-t1-state-store

  state-retention-days: 90

  terminal-action: finished

  initial-action: submit
```

Use the application's existing security/SSL/SASL configuration.

Do not overwrite existing Kafka properties accidentally.

---

# 29. Processing guarantee

Start with:

```text
at_least_once
```

unless your business requires exactly-once semantics.

At-least-once is simpler and generally sufficient if:

- downstream processing is idempotent
- duplicate output can be handled
- existing application already tolerates Kafka retries

Exactly-once can be considered later after validating the entire topology.

---

# 30. DLQ

Your DLQ producer is:

```java
KafkaTemplate<String, String>
```

Keep it separate.

The DLQ payload can contain:

```text
transaction_id
error type
error message
original payload
timestamp
source topic
partition
offset
```

Example conceptual DLQ JSON:

```json
{
  "transactionId": "ABC123",
  "errorType": "MISSING_TRANSACTION_STATE",
  "errorMessage": "T1 state not found",
  "sourceTopic": "input-topic",
  "partition": 2,
  "offset": 123456,
  "timestamp": 1780000000000
}
```

The exact DLQ strategy should follow your application's existing error-handling standard.

---

# 31. Important DLQ caveat

A normal Kafka Streams processor cannot simply call:

```java
dlqKafkaTemplate.send(...)
```

and assume the Streams topology has atomic behavior.

If the record is forwarded/committed while DLQ publishing fails, you can get inconsistent behavior.

For the first implementation, keep DLQ handling explicit and align it with your existing error-handling model.

If DLQ publishing must be atomic with the Kafka Streams transaction, we should design that separately.

---

# 32. T2-before-T1

Your normal ordering:

```text
T1 → T2 → T3 → T4
```

works naturally.

Rare case:

```text
T2 → T1 → T3 → T4
```

must not result in incomplete output.

Production solution:

```text
T2
 ↓
T1 not found
 ↓
durable pending-event handling
 ↓
T1 arrives
 ↓
T2 retried/reprocessed
 ↓
enrich
 ↓
output
```

Do not use JVM memory to park the event.

---

# 33. Existing producer

Your existing producer:

```java
KafkaTemplate<String, GenericRecord>
```

does not need to be replaced merely because Kafka Streams is introduced.

However, once the Kafka Streams topology is responsible for this flow, the preferred path is:

```text
KStream
   ↓
transformation
   ↓
KStream.to(outputTopic)
```

rather than:

```text
Kafka Streams
   ↓
KafkaTemplate.send(...)
```

This keeps the stream topology declarative and lets Kafka Streams manage the output producer.

Your existing `KafkaTemplate<String, GenericRecord>` can remain for other application paths.

---

# 34. Existing JSON.put logic

If your existing business logic does:

```java
genericRecord.put(
    "someField",
    value
);
```

that is perfectly compatible.

You can continue doing:

```java
GenericRecord enriched =
    enricher.enrich(
        currentEvent,
        t1Record
    );
```

The enrichment layer doesn't need to change to `Map<String,Object>`.

---

# 35. Do not introduce a JSON Map conversion

Do not introduce:

```text
GenericRecord
 ↓
Map<String,Object>
 ↓
GenericRecord
```

unless your existing business code specifically requires it.

That adds unnecessary:

- conversion
- memory allocation
- CPU
- garbage collection
- schema/type risks

Keep:

```text
GenericRecord → GenericRecord
```

throughout the main stream.

---

# 36. Final target data flow

```text
                         INPUT TOPIC
                              │
                              │
                              ▼
                    GenericRecord SerDe
                              │
                              ▼
                    KStream<String,
                       GenericRecord>
                              │
                              ▼
                  extract transaction_id
                              │
                              ▼
                     selectKey(transaction_id)
                              │
                              ▼
                    INTERNAL REPARTITION
                              │
                              ▼
                    STATEFUL PROCESSOR
                              │
                 ┌────────────┼────────────┐
                 │            │            │
               submit        T2/T3/...   finished
                 │            │            │
                 ▼            ▼            ▼
              save T1     lookup T1     lookup T1
                              │            │
                              ▼            ▼
                           enrich       enrich
                              │            │
                              └─────┬──────┘
                                    │
                                    ▼
                         GenericRecord enriched
                                    │
                                    ▼
                     Existing transformation
                                    │
                                    ▼
                         GenericRecord output
                                    │
                                    ▼
                             OUTPUT TOPIC
                                    │
                                    ▼
                            delete T1 state
```

---

# 37. What should happen to the old `@Async` executor

Do not migrate the executor configuration into Kafka Streams.

Old:

```text
core pool
max pool
queue
thread prefix
```

New:

```text
Kafka Streams threads
partitions
state store
Kafka buffering
```

If the executor is used elsewhere, retain it.

---

# 38. Production memory rules

Never do:

```java
private final Map<String, GenericRecord> state =
        new ConcurrentHashMap<>();
```

Never do:

```java
List<GenericRecord> pendingEvents;
```

without a hard bound.

Never do:

```java
@Async
CompletableFuture
```

inside the stateful processor.

Never keep a full Kafka backlog in an executor queue.

Use:

```text
Kafka
 +
Kafka Streams state store
 +
bounded processing
```

---

# 39. Production observability

Monitor at minimum:

### Kafka

- input consumer lag
- output producer latency
- repartition topic lag
- state changelog lag
- records/sec

### Kafka Streams

- task state
- rebalance count
- stream thread state
- processing latency
- skipped records
- restore duration

### State store

- number of active keys
- RocksDB disk usage
- state restore time
- changelog size

### JVM

- heap used
- heap committed
- GC frequency
- GC pause
- CPU
- container memory

### Business

- T1 count
- T2/T3/T4 count
- missing-T1 count
- terminal event count
- enrichment failures
- DLQ count

---

# 40. Migration plan

Do this incrementally.

## Phase 1 — infrastructure

Add:

```text
Kafka Streams dependency
Kafka Streams configuration
GenericRecord SerDe integration
state store configuration
```

## Phase 2 — minimal topology

Build:

```text
input
 ↓
GenericRecord
 ↓
selectKey(transaction_id)
 ↓
repartition
 ↓
output
```

Validate that the output is identical to the existing flow.

## Phase 3 — state

Add:

```text
submit
 ↓
state store
```

Validate state restoration after restart.

## Phase 4 — enrichment

Add:

```text
T2/T3/T4
 ↓
lookup T1
 ↓
enrich
```

## Phase 5 — existing transformation

Move/reuse the business logic from `AsyncProcessingService`.

## Phase 6 — terminal cleanup

```text
finished
 ↓
enrich
 ↓
output
 ↓
delete state
```

## Phase 7 — rare out-of-order case

Implement durable pending T2/T3/T4 handling.

## Phase 8 — cutover

Disable the old:

```text
@KafkaListener → @Async
```

flow for this input topic.

---

# 41. Validation checklist before production

## Functional

- [ ] T1 saves correctly
- [ ] T1 output is correct
- [ ] T2 uses T1
- [ ] T3 uses T1
- [ ] T4 uses T1
- [ ] More than four events work
- [ ] `finished` deletes state
- [ ] T2-before-T1 does not lose data
- [ ] transaction IDs are extracted from payload
- [ ] original Kafka record key is not incorrectly used as transaction ID

## Kafka

- [ ] Input partitions verified
- [ ] Output partitions verified
- [ ] Repartition topic permissions verified
- [ ] Changelog topic permissions verified
- [ ] Internal topic replication configured
- [ ] Application ID is unique
- [ ] Existing Kafka security configuration reused

## Serialization

- [ ] Input GenericRecord SerDe works
- [ ] Output GenericRecord SerDe works
- [ ] Schema Registry configuration is compatible
- [ ] No unnecessary GenericRecord → Map conversion
- [ ] Existing KafkaTemplate<String, GenericRecord> remains compatible

## Performance

- [ ] 34K/hour load tested
- [ ] 10K active transactions tested
- [ ] 10–12 KB T1 tested
- [ ] JVM heap monitored
- [ ] RocksDB disk monitored
- [ ] state restoration tested
- [ ] application restart tested
- [ ] rebalance tested

## Failure recovery

- [ ] Application restart after T1
- [ ] Application restart between T1/T2
- [ ] Kafka Streams state restoration
- [ ] broker outage
- [ ] consumer rebalance
- [ ] serialization error
- [ ] enrichment error
- [ ] DLQ behavior
- [ ] missing T1 behavior

---

# 42. Final class responsibility map

| Class | Responsibility |
|---|---|
| `KafkaConsumerService` | **No longer consumes this transaction topic** |
| `AsyncProcessingService` | **Business logic extracted/reused; `@Async` path removed for this flow** |
| `KafkaStreamsConfig` | Kafka Streams runtime configuration |
| `TransactionEnrichmentTopology` | Defines the stream topology |
| `GenericRecordSerdeProvider` | Reuses/configures existing GenericRecord serialization |
| `TransactionEnrichmentProcessor` | Stateful T1 lookup/save/delete |
| `TransactionState` | State representation |
| `TransactionStateSerde` | State-store serialization |
| `TransactionEnricher` | T1 → T2/T3/T4 enrichment rules |
| `ExistingTransformationAdapter` | Existing business transformation |
| `MissingTransactionStateException` | Missing T1 condition |
| Existing `KafkaTemplate<String, GenericRecord>` | Can remain for other producer flows |
| Existing `KafkaTemplate<String, String>` | DLQ producer |

---

# 43. Final architecture decision

The final design is:

```text
                 Kafka input
                     │
                     ▼
              Kafka Streams
                     │
          GenericRecord SerDe
                     │
                     ▼
          selectKey(transaction_id)
                     │
                     ▼
             Kafka repartition
                     │
                     ▼
           Persistent State Store
                     │
          ┌──────────┼───────────┐
          │          │           │
         T1       T2/T3/...   finished
          │          │           │
        save      lookup T1    lookup T1
                     │           │
                   enrich      enrich
                     │           │
                     └─────┬─────┘
                           ▼
                  Existing transformation
                           │
                           ▼
                  GenericRecord output
                           │
                           ▼
                    Output topic
                           │
                    finished cleanup
```

This keeps your existing `GenericRecord` model and producer contract, removes the need for a Redis/database, avoids an in-memory transaction map, and uses Kafka Streams for the stateful part that your current `@Async` design cannot safely provide.
