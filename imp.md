# Kafka Transaction Enrichment Module

Production-oriented skeleton for enriching T2/T3/T4 events with state captured from T1, using Kafka Streams persistent state, Avro/Schema Registry, transaction-ID repartitioning, durable retry, and terminal-state cleanup.

> **Important:** This is an integration skeleton, not a drop-in deployment. Replace the marked integration points with your existing Avro classes/SerDes, topic names, event fields, retry conventions, and existing producer/consumer contracts.

## 1. Target architecture

```text
Existing Input Topic
        |
        v
   Avro T1/T2/T3/T4
        |
        v
Kafka Streams
        |
        | selectKey(transactionId)
        v
Internal repartition topic
        |
        +----------------------+
        |                      |
        v                      v
       T1                  T2/T3/T4
        |                      |
        v                      v
T1StateMapper             lookup T1 state
        |                      |
        v                      |
Persistent State Store <-------+
        |
        +----> Kafka changelog (Kafka Streams managed)
        |
        v
   Enrichment
        |
        +---- missing T1 --> durable retry topic --> retry processing
        |
        v
 Existing Output Topic

Terminal event
      |
      v
Delete transaction state
```

### Key design choices

* The original Kafka record key is **not** used for correlation.
* The Avro payload's `transactionId` becomes the **internal Kafka Streams key**.
* Kafka Streams performs repartitioning when required for stateful processing.
* There is one **logical** state store. Kafka Streams may physically partition it across tasks.
* T1 state stores only the fields needed by later events, not necessarily the entire 10–12 KB T1.
* State is persisted locally using Kafka Streams' persistent store and backed by a Kafka changelog.
* No Redis, database, JVM `Map`, or unbounded in-memory waiting list is required.
* A late/missing T1 must not be silently dropped. The skeleton uses a durable retry topic.
* A terminal event removes state early; the retention/changelog policy remains a recovery safety mechanism.
* The expected peak of 34,000 messages/hour (~9.4 messages/sec) and ~10,000 simultaneous active transactions is modest for this architecture, assuming the enrichment itself is not CPU-heavy.

---

# 2. Directory structure

```text
src/
└── main/
    ├── avro/
    │   └── TransactionEnrichmentState.avsc
    │
    ├── java/
    │   └── com/
    │       └── yourcompany/
    │           └── enrichment/
    │               ├── config/
    │               │   ├── EnrichmentKafkaConfig.java
    │               │   └── EnrichmentTopology.java
    │               │
    │               ├── constants/
    │               │   └── EnrichmentConstants.java
    │               │
    │               ├── model/
    │               │   ├── TransactionEvent.java
    │               │   ├── T1State.java
    │               │   └── EnrichedTransaction.java
    │               │
    │               ├── service/
    │               │   ├── T1StateMapper.java
    │               │   ├── TransactionEnrichmentService.java
    │               │   └── RetryDecisionService.java
    │               │
    │               ├── transformer/
    │               │   └── MissingT1RetryTransformer.java
    │               │
    │               └── serde/
    │                   └── SerdeFactory.java
    │
    └── resources/
        └── application.yml
```

---

# 3. Maven dependencies

Add the dependencies compatible with your Spring Boot dependency management.

```xml
<dependencies>

    <!-- Existing application dependency, if not already present -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter</artifactId>
    </dependency>

    <!-- Spring Kafka -->
    <dependency>
        <groupId>org.springframework.kafka</groupId>
        <artifactId>spring-kafka</artifactId>
    </dependency>

    <!-- Kafka Streams -->
    <dependency>
        <groupId>org.apache.kafka</groupId>
        <artifactId>kafka-streams</artifactId>
    </dependency>

    <!-- Confluent Avro + Schema Registry -->
    <!-- Use versions compatible with your existing Kafka/Confluent stack. -->
    <dependency>
        <groupId>io.confluent</groupId>
        <artifactId>kafka-avro-serializer</artifactId>
        <version>${confluent.version}</version>
    </dependency>

</dependencies>
```

If your application already has the Avro serializer/Schema Registry dependencies, **do not duplicate them**. Use the versions already managed by your application.

---

# 4. Avro state schema

## Path

```text
src/main/avro/TransactionEnrichmentState.avsc
```

```json
{
  "type": "record",
  "name": "TransactionEnrichmentState",
  "namespace": "com.yourcompany.enrichment.avro",
  "fields": [
    {
      "name": "transactionId",
      "type": "string"
    },
    {
      "name": "customerId",
      "type": ["null", "string"],
      "default": null
    },
    {
      "name": "accountId",
      "type": ["null", "string"],
      "default": null
    },
    {
      "name": "paymentId",
      "type": ["null", "string"],
      "default": null
    },
    {
      "name": "amount",
      "type": ["null", "double"],
      "default": null
    },
    {
      "name": "currency",
      "type": ["null", "string"],
      "default": null
    }
  ]
}
```

**Do not copy this schema literally.** Add only fields from T1 that T2/T3/T4 actually require.

The generated Avro class is preferable to Java native serialization.

---

# 5. State-store logical table

There is no SQL table. The persistent state is a Kafka Streams key-value store.

Conceptually:

| Key | Value |
|---|---|
| `TX1001` | T1State for TX1001 |
| `TX1002` | T1State for TX1002 |
| `TX1003` | T1State for TX1003 |

The logical model is:

```text
Key:
    transactionId

Value:
    TransactionEnrichmentState
        customerId
        accountId
        paymentId
        amount
        currency
        ...
```

With ~10,000 simultaneously active transactions, this is expected to be a manageable state size, particularly if you store only required fields.

Physically, Kafka Streams can partition this logical state by task/partition. Your application does **not** manually manage those physical partitions.

---

# 6. Kafka topics

## Existing topics

```text
EXISTING_INPUT_TOPIC
    |
    | T1/T2/T3/T4
    v
Kafka Streams
    |
    v
EXISTING_OUTPUT_TOPIC
```

## Internal topics

Kafka Streams may create internal topics for:

1. **Repartitioning** after `selectKey(transactionId)`.
2. **State-store changelog** for recovery.

You should not treat these as application business topics.

### Retry topic

For a T2/T3/T4 arriving before its T1 state exists, use a durable retry mechanism.

Recommended logical flow:

```text
T2/T3/T4
    |
    v
T1 state found?
    |
    +---- YES ----> enrich -> output
    |
    +---- NO -----> retry topic
                         |
                         v
                    retry consumer
                         |
                         v
                   T1 now exists?
                     /       \
                   YES       NO
                    |         |
                    v         v
                 enrich     retry/DLQ
```

For production, create the retry topic with a bounded retry policy and a DLQ. Do not keep missing events in JVM memory.

---

# 7. Constants

## Path

```text
src/main/java/com/yourcompany/enrichment/constants/EnrichmentConstants.java
```

```java
package com.yourcompany.enrichment.constants;

public final class EnrichmentConstants {

    private EnrichmentConstants() {
    }

    public static final String INPUT_TOPIC =
            "YOUR_EXISTING_INPUT_TOPIC";

    public static final String OUTPUT_TOPIC =
            "YOUR_EXISTING_OUTPUT_TOPIC";

    public static final String RETRY_TOPIC =
            "YOUR_ENRICHMENT_RETRY_TOPIC";

    public static final String DLQ_TOPIC =
            "YOUR_ENRICHMENT_DLQ_TOPIC";

    public static final String APPLICATION_ID =
            "transaction-enrichment-stream";

    public static final String T1_STATE_STORE =
            "transaction-t1-state-store";
}
```

In the final application, move these to configuration rather than hardcoding them.

---

# 8. Transaction event abstraction

## Path

```text
src/main/java/com/yourcompany/enrichment/model/TransactionEvent.java
```

```java
package com.yourcompany.enrichment.model;

/**
 * Skeleton only.
 *
 * In the real application, replace this with your existing Avro
 * GenericRecord or generated SpecificRecord.
 */
public class TransactionEvent {

    private String transactionId;
    private String eventType;
    private String eventId;
    private Long eventTimestamp;

    // Replace with your actual event/payload model.
    private Object payload;

    public TransactionEvent() {
    }

    public String getTransactionId() {
        return transactionId;
    }

    public void setTransactionId(String transactionId) {
        this.transactionId = transactionId;
    }

    public String getEventType() {
        return eventType;
    }

    public void setEventType(String eventType) {
        this.eventType = eventType;
    }

    public String getEventId() {
        return eventId;
    }

    public void setEventId(String eventId) {
        this.eventId = eventId;
    }

    public Long getEventTimestamp() {
        return eventTimestamp;
    }

    public void setEventTimestamp(Long eventTimestamp) {
        this.eventTimestamp = eventTimestamp;
    }

    public Object getPayload() {
        return payload;
    }

    public void setPayload(Object payload) {
        this.payload = payload;
    }
}
```

If your current application already uses `GenericRecord`, don't create this duplicate model just to follow the example. Use your actual Avro type.

---

# 9. T1 state

## Path

```text
src/main/java/com/yourcompany/enrichment/model/T1State.java
```

```java
package com.yourcompany.enrichment.model;

import java.math.BigDecimal;

/**
 * If Avro code generation is used, this Java model can be replaced
 * by the generated Avro TransactionEnrichmentState class.
 */
public class T1State {

    private String transactionId;

    private String customerId;
    private String accountId;
    private String paymentId;

    private BigDecimal amount;
    private String currency;

    public T1State() {
    }

    public String getTransactionId() {
        return transactionId;
    }

    public void setTransactionId(String transactionId) {
        this.transactionId = transactionId;
    }

    public String getCustomerId() {
        return customerId;
    }

    public void setCustomerId(String customerId) {
        this.customerId = customerId;
    }

    public String getAccountId() {
        return accountId;
    }

    public void setAccountId(String accountId) {
        this.accountId = accountId;
    }

    public String getPaymentId() {
        return paymentId;
    }

    public void setPaymentId(String paymentId) {
        this.paymentId = paymentId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public void setAmount(BigDecimal amount) {
        this.amount = amount;
    }

    public String getCurrency() {
        return currency;
    }

    public void setCurrency(String currency) {
        this.currency = currency;
    }
}
```

---

# 10. Enriched output model

## Path

```text
src/main/java/com/yourcompany/enrichment/model/EnrichedTransaction.java
```

```java
package com.yourcompany.enrichment.model;

/**
 * Skeleton.
 *
 * In your implementation this will likely be your existing Avro
 * output record rather than a new Java object.
 */
public class EnrichedTransaction {

    private String transactionId;
    private String eventType;

    private Object payload;

    public EnrichedTransaction() {
    }

    public String getTransactionId() {
        return transactionId;
    }

    public void setTransactionId(String transactionId) {
        this.transactionId = transactionId;
    }

    public String getEventType() {
        return eventType;
    }

    public void setEventType(String eventType) {
        this.eventType = eventType;
    }

    public Object getPayload() {
        return payload;
    }

    public void setPayload(Object payload) {
        this.payload = payload;
    }
}
```

---

# 11. T1 state mapper

## Path

```text
src/main/java/com/yourcompany/enrichment/service/T1StateMapper.java
```

```java
package com.yourcompany.enrichment.service;

import com.yourcompany.enrichment.model.T1State;
import com.yourcompany.enrichment.model.TransactionEvent;

import org.springframework.stereotype.Component;

@Component
public class T1StateMapper {

    public T1State map(TransactionEvent event) {

        if (event == null) {
            throw new IllegalArgumentException("T1 event cannot be null");
        }

        if (event.getTransactionId() == null ||
                event.getTransactionId().isBlank()) {

            throw new IllegalArgumentException(
                    "T1 transactionId cannot be null/blank"
            );
        }

        T1State state = new T1State();

        state.setTransactionId(event.getTransactionId());

        /*
         * TODO:
         *
         * Extract ONLY the fields required to enrich T2/T3/T4.
         *
         * Example:
         *
         * state.setCustomerId(
         *     extractString(event, "customerId")
         * );
         *
         * state.setAccountId(...);
         * state.setPaymentId(...);
         * state.setAmount(...);
         * state.setCurrency(...);
         */

        return state;
    }
}
```

---

# 12. Enrichment service

## Path

```text
src/main/java/com/yourcompany/enrichment/service/TransactionEnrichmentService.java
```

```java
package com.yourcompany.enrichment.service;

import com.yourcompany.enrichment.model.T1State;
import com.yourcompany.enrichment.model.TransactionEvent;

import org.springframework.stereotype.Service;

/**
 * Stateless business logic.
 *
 * IMPORTANT:
 * Do not add a Map/cache/list of transactions here.
 * Kafka Streams owns the persistent state.
 */
@Service
public class TransactionEnrichmentService {

    public TransactionEvent enrich(
            TransactionEvent event,
            T1State state) {

        if (event == null) {
            return null;
        }

        if (state == null) {
            throw new MissingT1StateException(
                    event.getTransactionId()
            );
        }

        /*
         * TODO:
         *
         * Populate the current T2/T3/T4 event from T1 state.
         *
         * Example:
         *
         * setField(event, "customerId", state.getCustomerId());
         * setField(event, "accountId", state.getAccountId());
         * setField(event, "amount", state.getAmount());
         */

        return event;
    }
}
```

---

# 13. Missing T1 exception

## Path

```text
src/main/java/com/yourcompany/enrichment/service/MissingT1StateException.java
```

```java
package com.yourcompany.enrichment.service;

public class MissingT1StateException extends RuntimeException {

    public MissingT1StateException(String transactionId) {
        super("T1 state not found for transactionId=" + transactionId);
    }
}
```

---

# 14. Retry decision service

## Path

```text
src/main/java/com/yourcompany/enrichment/service/RetryDecisionService.java
```

```java
package com.yourcompany.enrichment.service;

import com.yourcompany.enrichment.model.TransactionEvent;

import org.springframework.stereotype.Component;

@Component
public class RetryDecisionService {

    /*
     * Keep retry policy bounded.
     *
     * Do not retry forever.
     */
    private static final int MAX_RETRIES = 5;

    public boolean shouldRetry(TransactionEvent event) {

        int retryCount = extractRetryCount(event);

        return retryCount < MAX_RETRIES;
    }

    public int extractRetryCount(TransactionEvent event) {

        /*
         * TODO:
         *
         * Read retry count from your event/header/envelope.
         *
         * Return 0 when this is the first attempt.
         */
        return 0;
    }

    public TransactionEvent incrementRetryCount(
            TransactionEvent event) {

        /*
         * TODO:
         *
         * Increment retry metadata in the format your
         * existing application uses.
         */
        return event;
    }
}
```

---

# 15. Kafka Streams configuration

## Path

```text
src/main/java/com/yourcompany/enrichment/config/EnrichmentKafkaConfig.java
```

```java
package com.yourcompany.enrichment.config;

import com.yourcompany.enrichment.constants.EnrichmentConstants;

import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.StreamsConfig;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import org.springframework.kafka.config.KafkaStreamsConfiguration;
import org.springframework.kafka.config.KafkaStreamsDefaultConfiguration;

import java.util.HashMap;
import java.util.Map;

@Configuration
public class EnrichmentKafkaConfig {

    @Value("${spring.kafka.bootstrap-servers}")
    private String bootstrapServers;

    @Value("${spring.kafka.properties.schema.registry.url}")
    private String schemaRegistryUrl;

    @Bean(
        name = KafkaStreamsDefaultConfiguration
                .DEFAULT_STREAMS_CONFIG_BEAN_NAME
    )
    public KafkaStreamsConfiguration kafkaStreamsConfiguration() {

        Map<String, Object> props = new HashMap<>();

        props.put(
                StreamsConfig.APPLICATION_ID_CONFIG,
                EnrichmentConstants.APPLICATION_ID
        );

        props.put(
                StreamsConfig.BOOTSTRAP_SERVERS_CONFIG,
                bootstrapServers
        );

        /*
         * Internal Kafka Streams key after selectKey().
         */
        props.put(
                StreamsConfig.DEFAULT_KEY_SERDE_CLASS_CONFIG,
                Serdes.String().getClass()
        );

        /*
         * State is persisted locally.
         *
         * IMPORTANT:
         * Use a persistent disk volume in production.
         */
        props.put(
                StreamsConfig.STATE_DIR_CONFIG,
                "/var/lib/app/kafka-streams"
        );

        /*
         * Placeholder.
         *
         * Tune based on the actual partition count and deployment
         * topology.
         */
        props.put(
                StreamsConfig.NUM_STREAM_THREADS_CONFIG,
                1
        );

        /*
         * Use the guarantee appropriate for your Kafka cluster and
         * current producer semantics.
         *
         * Start with at-least-once unless exactly-once has been
         * explicitly validated in your environment.
         */
        props.put(
                StreamsConfig.PROCESSING_GUARANTEE_CONFIG,
                StreamsConfig.AT_LEAST_ONCE
        );

        /*
         * Internal topic replication.
         *
         * Requires broker/environment support.
         */
        props.put(
                StreamsConfig.REPLICATION_FACTOR_CONFIG,
                3
        );

        /*
         * Bounded internal cache.
         *
         * This is NOT the transaction state store.
         */
        props.put(
                StreamsConfig.STATESTORE_CACHE_MAX_BYTES_CONFIG,
                10 * 1024 * 1024L
        );

        /*
         * Commit frequency.
         *
         * Tune with load testing.
         */
        props.put(
                StreamsConfig.COMMIT_INTERVAL_MS_CONFIG,
                100
        );

        /*
         * Avro / Schema Registry.
         *
         * Your existing serializer configuration can be merged here.
         */
        props.put(
                "schema.registry.url",
                schemaRegistryUrl
        );

        return new KafkaStreamsConfiguration(props);
    }
}
```

---

# 16. Avro SerDes factory

## Path

```text
src/main/java/com/yourcompany/enrichment/serde/SerdeFactory.java
```

```java
package com.yourcompany.enrichment.serde;

import io.confluent.kafka.streams.serdes.avro.GenericAvroSerde;

import org.apache.kafka.common.serialization.Serde;

import java.util.Map;

public final class SerdeFactory {

    private SerdeFactory() {
    }

    public static Serde<Object> genericAvroSerde(
            String schemaRegistryUrl) {

        GenericAvroSerde serde = new GenericAvroSerde();

        serde.configure(
                Map.of(
                        "schema.registry.url",
                        schemaRegistryUrl
                ),
                false
        );

        return (Serde<Object>) (Serde<?>) serde;
    }
}
```

### Note

If your current application already has correctly configured Avro SerDes, **reuse those** instead of introducing another factory.

The exact type should match your existing `GenericRecord`/SpecificRecord setup.

---

# 17. Main Kafka Streams topology

## Path

```text
src/main/java/com/yourcompany/enrichment/config/EnrichmentTopology.java
```

```java
package com.yourcompany.enrichment.config;

import com.yourcompany.enrichment.constants.EnrichmentConstants;
import com.yourcompany.enrichment.model.T1State;
import com.yourcompany.enrichment.model.TransactionEvent;
import com.yourcompany.enrichment.service.T1StateMapper;
import com.yourcompany.enrichment.service.TransactionEnrichmentService;

import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.common.utils.Bytes;

import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.Grouped;
import org.apache.kafka.streams.kstream.Joined;
import org.apache.kafka.streams.kstream.KStream;
import org.apache.kafka.streams.kstream.KTable;
import org.apache.kafka.streams.kstream.Materialized;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.state.KeyValueStore;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class EnrichmentTopology {

    private final T1StateMapper t1StateMapper;
    private final TransactionEnrichmentService enrichmentService;

    public EnrichmentTopology(
            T1StateMapper t1StateMapper,
            TransactionEnrichmentService enrichmentService) {

        this.t1StateMapper = t1StateMapper;
        this.enrichmentService = enrichmentService;
    }

    @Bean
    public KStream<String, TransactionEvent>
    transactionEnrichmentStream(
            StreamsBuilder builder) {

        /*
         * ========================================================
         * 1. Read existing topic.
         * ========================================================
         */

        KStream<String, TransactionEvent> input =
                builder.stream(
                        EnrichmentConstants.INPUT_TOPIC,
                        Consumed.with(
                                Serdes.String(),

                                /*
                                 * TODO:
                                 * Replace with your actual Avro
                                 * event serde.
                                 */
                                transactionEventSerde()
                        )
                );


        /*
         * ========================================================
         * 2. Re-key by BUSINESS TRANSACTION ID.
         *
         * The original Kafka key is irrelevant to correlation.
         *
         * After this:
         *
         * TX123 -> T1
         * TX123 -> T2
         * TX123 -> T3
         * TX123 -> T4
         *
         * Kafka Streams will create/use a repartition topic when
         * required by downstream stateful processing.
         * ========================================================
         */

        KStream<String, TransactionEvent> transactionStream =
                input.selectKey(
                        (originalKey, event) ->
                                event.getTransactionId()
                );


        /*
         * ========================================================
         * 3. T1 stream.
         * ========================================================
         */

        KStream<String, TransactionEvent> t1Stream =
                transactionStream.filter(
                        (key, event) ->
                                event != null
                                        && isT1(event)
                        );


        /*
         * ========================================================
         * 4. Subsequent events.
         * ========================================================
         */

        KStream<String, TransactionEvent> subsequentStream =
                transactionStream.filter(
                        (key, event) ->
                                event != null
                                        && !isT1(event)
                        );


        /*
         * ========================================================
         * 5. Convert T1 into the compact state representation.
         * ========================================================
         */

        KTable<String, T1State> t1StateTable =
                t1Stream
                        .mapValues(
                                t1StateMapper::map
                        )
                        .toTable(
                                Materialized
                                        .<String, T1State,
                                                KeyValueStore<
                                                        Bytes, byte[]>>as(
                                                EnrichmentConstants
                                                        .T1_STATE_STORE
                                        )
                                        .withKeySerde(
                                                Serdes.String()
                                        )
                                        .withValueSerde(
                                                t1StateSerde()
                                        )
                        );


        /*
         * ========================================================
         * 6. Enrich T2/T3/T4 using T1 state.
         *
         * IMPORTANT:
         * A normal KTable join does not wait indefinitely for a
         * missing T1. Therefore the production implementation
         * needs a durable retry/reprocessing path for missing T1.
         *
         * This join is the fast path for the normal case.
         * ========================================================
         */

        KStream<String, TransactionEvent> enriched =
                subsequentStream.join(
                        t1StateTable,

                        (event, t1State) ->
                                enrichmentService.enrich(
                                        event,
                                        t1State
                                ),

                        Joined.with(
                                Serdes.String(),
                                transactionEventSerde(),
                                t1StateSerde()
                        )
                );


        /*
         * ========================================================
         * 7. Existing output topic.
         * ========================================================
         */

        enriched.to(
                EnrichmentConstants.OUTPUT_TOPIC,
                Produced.with(
                        Serdes.String(),
                        transactionEventSerde()
                )
        );

        return enriched;
    }


    private boolean isT1(TransactionEvent event) {

        return "T1".equals(event.getEventType());
    }


    private org.apache.kafka.common.serialization.Serde<
            TransactionEvent> transactionEventSerde() {

        /*
         * TODO:
         *
         * Return your existing Avro GenericRecord/SpecificRecord
         * serde.
         */
        throw new UnsupportedOperationException(
                "Integrate existing transaction Avro serde"
        );
    }


    private org.apache.kafka.common.serialization.Serde<T1State>
    t1StateSerde() {

        /*
         * TODO:
         *
         * Prefer generated Avro TransactionEnrichmentState +
         * appropriate Avro serde in production.
         */
        throw new UnsupportedOperationException(
                "Integrate T1 state Avro serde"
        );
    }
}
```

---

# 18. Important limitation of the simple join

The code above represents the **normal fast path**:

```text
T1
 ↓
state materialized
 ↓
T2
 ↓
join
 ↓
enriched output
```

But this:

```text
T2
 ↓
T1 not yet materialized
```

must not disappear.

A KTable join is not a "wait until T1 exists" operation.

Therefore, use the following production pattern.

---

# 19. Durable missing-T1 retry

## Recommended flow

```text
                    T2/T3/T4
                         |
                         v
                  T1 state exists?
                    /          \
                  YES          NO
                   |            |
                   v            v
                Enrich      Retry Topic
                   |            |
                   v            v
                Output       Retry delay
                                |
                                v
                          Check T1 again
                                |
                       +--------+--------+
                       |                 |
                      YES               NO
                       |                 |
                       v                 v
                    Enrich            retry again
                                      /       \
                                   limit      limit
                                    not         hit
                                   hit          |
                                    |           v
                                    +--------> DLQ
```

The retry topic should carry:

```text
transactionId
eventId
eventType
original Avro payload
retryCount
firstSeenTimestamp
lastRetryTimestamp
```

Do **not** put waiting events into:

```java
Map<String, List<TransactionEvent>>
```

or an executor queue.

---

# 20. Retry topic implementation options

There are two good ways to implement this.

### Option A: Existing retry infrastructure

If your application already has retry/DLT infrastructure, **reuse it**.

This is preferred.

### Option B: Kafka retry topics

Create something such as:

```text
transaction-enrichment-retry-1
transaction-enrichment-retry-2
transaction-enrichment-retry-3
transaction-enrichment-dlt
```

with controlled delays/backoff.

The exact retry implementation depends on whether your current application already uses Spring Kafka's retry-topic support.

---

# 21. Terminal event

Add this logic to the final topology/business flow.

Conceptually:

```java
if (isTerminalEvent(event)) {
    deleteTransactionState(event.getTransactionId());
}
```

The exact state deletion implementation depends on whether you use a KTable topology or a directly accessed `ReadOnlyKeyValueStore`.

Do not leave completed transactions in the store for 90 days if you already know they are terminal.

---

# 22. application.yml

## Path

```text
src/main/resources/application.yml
```

```yaml
spring:

  kafka:
    bootstrap-servers: ${KAFKA_BOOTSTRAP_SERVERS}

    properties:
      schema.registry.url: ${SCHEMA_REGISTRY_URL}

    streams:

      application-id: transaction-enrichment-stream

      properties:

        # Start with at-least-once unless exactly-once is required
        # and validated in your environment.
        processing.guarantee: at_least_once

        # Persistent state location.
        # IMPORTANT: production deployment must provide persistent
        # local disk with enough capacity.
        state.dir: ${KAFKA_STREAMS_STATE_DIR:/var/lib/app/kafka-streams}

        # Internal topic replication.
        replication.factor: 3

        # Start conservatively; tune after partition count is known.
        num.stream.threads: 1

        # Kafka Streams internal cache.
        # This is bounded memory and is NOT the T1 state store.
        cache.max.bytes.buffering: 10485760

        # Commit interval; tune with load testing.
        commit.interval.ms: 100

        # Keep state store/changelog behavior aligned with your
        # Kafka cluster policies.
```

---

# 23. Memory-safety rules

These are mandatory for this design.

### Never do this

```java
private final Map<String, T1State> cache =
        new ConcurrentHashMap<>();
```

### Never do this

```java
private final List<TransactionEvent> waitingEvents =
        new ArrayList<>();
```

### Never do this

```java
executor.submit(() -> {
    // unlimited event backlog
});
```

### Instead

```text
Persistent state
       +
Kafka retry topic
       +
bounded Kafka Streams cache
```

That means JVM heap is not your transaction database.

---

# 24. State sizing

Your stated workload:

```text
Peak events/hour ≈ 34,000
Peak events/sec  ≈ 9.4
Active txns      ≈ 10,000
T1 size          ≈ 10–12 KB
```

If only ~3 KB of each T1 is retained:

```text
10,000 × 3 KB
≈ 30 MB raw state
```

Even if you retain the complete 12 KB:

```text
10,000 × 12 KB
≈ 120 MB raw payload
```

The actual RocksDB disk footprint will be larger due to indexes, files, compaction, metadata, and temporary space, so size the disk with headroom.

The important point is that you should size around **simultaneously active state**, not:

```text
34,000 messages/hour × 90 days
```

if terminal events remove state promptly.

---

# 25. Why a single logical state store is okay

Your application sees:

```text
transaction-t1-state-store

TX001 -> T1State
TX002 -> T1State
TX003 -> T1State
...
TX10000 -> T1State
```

You don't create a separate store per partition.

Kafka Streams internally distributes it according to its tasks.

For example:

```text
Input topic
P0 P1 P2 P3

      |
      v

Kafka Streams

Task 0 -> state for P0/P1
Task 1 -> state for P2/P3
```

You don't manage this manually.

---

# 26. Why transactionId must become the processing key

Your current record might look like:

```text
Kafka key:
    ABC-999

Avro value:
    transactionId = TX123
    eventType = T2
```

T1 might be:

```text
Kafka key:
    XYZ-111

Avro value:
    transactionId = TX123
    eventType = T1
```

The existing Kafka keys don't correlate the transaction.

Therefore:

```java
input.selectKey(
    (key, event) -> event.getTransactionId()
);
```

changes the internal processing key to:

```text
TX123 -> T1
TX123 -> T2
TX123 -> T3
TX123 -> T4
```

Kafka Streams can then repartition by `TX123` for stateful processing.

---

# 27. Important: re-keying does not modify your original input topic

The original topic remains unchanged.

You are effectively doing:

```text
Existing topic
      |
      v
read original key/value
      |
      v
selectKey(transactionId)
      |
      v
internal repartition topic
```

The existing producer does not need to change just because the enrichment module internally re-keys.

---

# 28. Async application integration

Do not add another arbitrary `@Async` layer around Kafka Streams.

Avoid:

```text
Kafka Streams
     |
     v
@Async
     |
     v
ThreadPoolTaskExecutor
     |
     v
Enrichment
```

Prefer:

```text
Kafka Streams task
     |
     v
T1 state lookup
     |
     v
stateless enrichment
     |
     v
Kafka output
```

Kafka Streams provides concurrency through:

```text
partitions
+
tasks
+
stream threads
+
application instances
```

If your existing application has a separate asynchronous business flow outside Kafka Streams, keep that isolated.

---

# 29. Existing Avro/Schema Registry integration

Since Schema Registry already exists, use it.

Do not create a second local schema-management system unless your organization explicitly wants that.

Recommended:

```text
Existing event schema
        |
        v
Schema Registry

TransactionEnrichmentState schema
        |
        v
Schema Registry
```

The T1 state schema should be independently versioned and contain only the enrichment fields.

If your existing application uses `GenericRecord`, the final implementation can use `GenericRecord` for both event and state. If you use generated `SpecificRecord`, use generated Avro classes.

---

# 30. Production configuration still to be tuned

Do not finalize these blindly:

```text
num.stream.threads
processing.guarantee
cache.max.bytes.buffering
commit.interval.ms
replication.factor
retry count
retry delay
state disk size
```

The most important missing deployment input is the **input topic partition count**.

For example:

```text
2 partitions
4 partitions
8 partitions
12 partitions
```

changes the amount of useful parallelism.

Your current traffic (~9.4 messages/sec peak) does not require a huge partition count, but partitions determine how much the application can scale horizontally.

---

# 31. Production behavior for the normal case

```text
T1 TX100
 |
 +--> state store:
      TX100 -> {customerId, accountId, amount, ...}

T2 TX100
 |
 +--> lookup TX100
 |
 +--> copy T1 fields
 |
 +--> existing transformation
 |
 +--> output

T3 TX100
 |
 +--> lookup TX100
 |
 +--> copy T1 fields
 |
 +--> existing transformation
 |
 +--> output

T4 TX100
 |
 +--> lookup TX100
 |
 +--> copy T1 fields
 |
 +--> existing transformation
 |
 +--> output

Terminal TX100
 |
 +--> delete TX100 state
```

---

# 32. Production behavior for rare out-of-order case

```text
T2 TX100
 |
 +--> lookup TX100
 |
 +--> NOT FOUND
 |
 +--> durable retry topic
 |
 |
T1 TX100 arrives
 |
 +--> state store updated
 |
 |
retry T2 TX100
 |
 +--> lookup TX100
 |
 +--> FOUND
 |
 +--> enrich
 |
 +--> output
```

No JVM waiting list is involved.

---

# 33. What you need to replace

Search for every:

```text
TODO
```

and provide:

1. Actual input topic.
2. Actual output topic.
3. Existing Avro event type.
4. Existing Avro serde.
5. T1 field extraction.
6. T2/T3/T4 enrichment mapping.
7. Terminal event condition.
8. Existing retry/DLT mechanism.
9. Kafka partition count.
10. Production state directory.
11. Existing Schema Registry configuration.

---

# 34. Recommended implementation order

Don't implement everything simultaneously.

### Phase 1

Get this working:

```text
Input
  ↓
selectKey(transactionId)
  ↓
T1 → state
  ↓
T2/T3/T4 → lookup
  ↓
enrich
  ↓
output
```

### Phase 2

Add:

```text
missing T1
    ↓
retry topic
```

### Phase 3

Add:

```text
terminal event
    ↓
state deletion
```

### Phase 4

Tune:

```text
threads
cache
commit
partitions
state disk
retry
```

### Phase 5

Testing and failure scenarios.

---

# 35. Final recommendation

For your stated constraints, I would **not add Redis, a database, an application-level cache, or a new manually managed state topic**.

The target architecture is:

```text
                  Existing Kafka Topic
                          |
                          v
                     Avro Event
                          |
                          v
                selectKey(transactionId)
                          |
                          v
              Kafka Streams Repartition
                          |
              +-----------+-----------+
              |                       |
              v                       v
             T1                    T2/T3/T4
              |                       |
              v                       v
         Compact T1 State        T1 State Lookup
              |                       |
              +-----------+-----------+
                          |
                          v
                       Enrich
                          |
                +---------+---------+
                |                   |
             success             missing T1
                |                   |
                v                   v
             Output            Kafka Retry
                                    |
                                    v
                               Re-process
                                    |
                                    v
                               DLQ if exhausted

Terminal event
      |
      v
Delete T1 state
```

This keeps transaction state **inside Kafka Streams**, keeps JVM memory bounded, uses your existing Avro/Schema Registry infrastructure, handles your different original Kafka record key, and gives you a durable path for the rare case where T2/T3/T4 arrives before T1.
