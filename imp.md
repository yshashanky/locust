# Kafka Streams Enrichment — Simplified Final Implementation

## 1. First: two important clarifications

### A. Your producer already uses Avro serialization through configuration

You do **not** have custom serialization code in the producer.

Your configuration is effectively:

```properties
producer.key.serializer=org.apache.kafka.common.serialization.StringSerializer
producer.value.serializer=io.confluent.kafka.serializers.KafkaAvroSerializer
```

and your producer is:

```java
KafkaTemplate<String, GenericRecord>
```

That is completely normal.

`KafkaTemplate` does not need you to call `serialize()` manually. Spring Kafka passes the `GenericRecord` to the configured `KafkaAvroSerializer`.

### What this means for Kafka Streams

Kafka Streams is different because it directly reads/writes Kafka records.

For the input topic:

```text
String / String
```

use:

```java
Consumed.with(
    Serdes.String(),
    Serdes.String()
)
```

No Avro SerDe is needed for input.

For the output topic:

```text
String / GenericRecord
```

Kafka Streams needs a value SerDe.

**Do not create a new custom serializer.**

Configure the Kafka Streams Avro SerDe using the same Kafka Avro serializer configuration that your application already has:

```text
schema.registry.url
specific.avro.reader = false
auto.register.schemas = ...
use.latest.version = ...
subject.name.strategy = ...
authentication settings, if any
```

Use the exact values already present in your application's producer configuration.

The business code still does not manually serialize anything.

---

## 2. Second: `TransactionState` does NOT need to be your output Avro schema

The `TransactionState` mentioned earlier is an **internal Kafka Streams state-store value**.

It is not the same thing as your output `GenericRecord`.

You therefore do **not** need to create an Avro schema locally for it.

The cleanest approach for your case is:

```text
Input JSON String
       ↓
extract transaction_id
       ↓
T1 JSON payload
       ↓
State Store
```

The state store can retain the T1 payload in a compact internal representation.

For the first implementation, use:

```java
TransactionState {
    String transactionId;
    String t1Payload;
}
```

This avoids creating a local Avro schema for the state.

If your enrichment requires only a few T1 fields, later reduce this to only those fields. That will reduce state size.

The **output** `GenericRecord` is different:

```text
enriched JSON/model
       ↓
your existing SchemaProvider
       ↓
schema from Schema Registry
       ↓
GenericRecord
       ↓
KafkaAvroSerializer
       ↓
output topic
```

So your existing `SchemaProvider` should be reused.

---

# 3. Final data types

| Area | Type |
|---|---|
| Input topic | `String / String` |
| Kafka Streams input | `KStream<String, String>` |
| Internal parsed event | simple Java object |
| State key | `String transactionId` |
| State value | `TransactionState` |
| Output topic | `String / GenericRecord` |
| Existing output producer | `KafkaTemplate<String, GenericRecord>` |
| DLQ | `String / String` |
| Existing DLQ producer | `KafkaTemplate<String, String>` |

---

# 4. Do NOT add these things

For this implementation, you do **not** need:

```text
Redis
Database
Custom Avro serializer
Custom Avro deserializer for input
Local copy of the output Avro schema
GenericRecord state model
Map<String,Object> conversion everywhere
Async executor inside Kafka Streams
Another Kafka business topic
```

Kafka Streams will create its required internal repartition/changelog topics automatically.

---

# 5. Files in execution order

Use this order while implementing:

```text
1. KafkaStreamsConfig.java
2. TransactionState.java
3. TransactionStateSerde.java
4. TransactionEvent.java
5. TransactionEventParser.java
6. TransactionEnricher.java
7. TransactionEnrichmentProcessor.java
8. TransactionEnrichmentTopology.java
9. Existing SchemaProvider integration
10. Existing AsyncProcessingService integration/removal
```

Below is the minimal implementation structure.

---

# 6. File 1 — `KafkaStreamsConfig.java`

Path:

```text
src/main/java/<your-package>/config/KafkaStreamsConfig.java
```

Purpose:

- Kafka Streams configuration
- Input/output SerDe configuration
- State-store SerDe configuration

```java
package <your-package>.config;

import io.confluent.kafka.streams.serdes.avro.GenericAvroSerde;
import org.apache.kafka.common.serialization.Serdes;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.HashMap;
import java.util.Map;

@Configuration
public class KafkaStreamsConfig {

    /*
     * IMPORTANT:
     *
     * Reuse the same Schema Registry properties already present
     * in your application's Kafka producer configuration.
     */
    @Bean
    public GenericAvroSerde genericAvroSerde() {

        GenericAvroSerde serde = new GenericAvroSerde();

        Map<String, Object> config = new HashMap<>();

        config.put(
                "schema.registry.url",
                "${schema.registry.url}"
        );

        /*
         * TODO:
         *
         * Do NOT literally use "${schema.registry.url}" here.
         * Inject your existing application property instead.
         *
         * Example:
         *
         * @Value("${spring.kafka.properties.schema.registry.url}")
         *
         * or use Environment.
         */

        serde.configure(config, false);

        return serde;
    }

    /*
     * TransactionState uses a simple String payload.
     *
     * We will use:
     *
     * key   = String
     * value = String
     *
     * for the state store.
     */
    @Bean
    public Serdes.StringSerde transactionStateSerde() {
        return new Serdes.StringSerde();
    }
}
```

### Important correction

The above bean is only the configuration location.

Because your exact property names are already present in your application, **do not duplicate them blindly**.

Prefer injecting the existing properties.

For example:

```java
@Value("${spring.kafka.properties.schema.registry.url}")
private String schemaRegistryUrl;
```

Then:

```java
config.put(
    "schema.registry.url",
    schemaRegistryUrl
);
```

If your existing producer configuration already exposes the full Kafka properties map, reuse that map instead of maintaining a second copy.

---

# 7. File 2 — `TransactionState.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionState.java
```

Keep this extremely small.

```java
package <your-package>.enrichment;

public class TransactionState {

    private final String transactionId;
    private final String t1Payload;

    public TransactionState(
            String transactionId,
            String t1Payload) {

        this.transactionId = transactionId;
        this.t1Payload = t1Payload;
    }

    public String getTransactionId() {
        return transactionId;
    }

    public String getT1Payload() {
        return t1Payload;
    }
}
```

### Why this works

This is **not an Avro record**.

It is merely your application's internal state representation.

You do not need to load the output topic schema for this.

---

# 8. File 3 — `TransactionStateSerde.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionStateSerde.java
```

For a simple state model, serialize the two fields as JSON.

```java
package <your-package>.enrichment;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.common.serialization.Deserializer;
import org.apache.kafka.common.serialization.Serde;
import org.apache.kafka.common.serialization.Serializer;

import java.io.IOException;

public class TransactionStateSerde
        implements Serde<TransactionState> {

    private final ObjectMapper objectMapper =
            new ObjectMapper();

    @Override
    public Serializer<TransactionState> serializer() {

        return (topic, state) -> {

            if (state == null) {
                return null;
            }

            try {
                return objectMapper.writeValueAsBytes(
                        state
                );
            } catch (JsonProcessingException e) {
                throw new IllegalStateException(
                        "Unable to serialize TransactionState",
                        e
                );
            }
        };
    }

    @Override
    public Deserializer<TransactionState> deserializer() {

        return (topic, bytes) -> {

            if (bytes == null) {
                return null;
            }

            try {
                return objectMapper.readValue(
                        bytes,
                        TransactionState.class
                );
            } catch (IOException e) {
                throw new IllegalStateException(
                        "Unable to deserialize TransactionState",
                        e
                );
            }
        };
    }
}
```

### Important

This does **not** serialize the final output record.

It only serializes the state maintained by Kafka Streams.

---

# 9. File 4 — `TransactionEvent.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionEvent.java
```

Keep this minimal.

```java
package <your-package>.enrichment;

public class TransactionEvent {

    private final String transactionId;
    private final String action;
    private final String payload;

    public TransactionEvent(
            String transactionId,
            String action,
            String payload) {

        this.transactionId = transactionId;
        this.action = action;
        this.payload = payload;
    }

    public String getTransactionId() {
        return transactionId;
    }

    public String getAction() {
        return action;
    }

    public String getPayload() {
        return payload;
    }
}
```

---

# 10. File 5 — `TransactionEventParser.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionEventParser.java
```

Use the JSON library already present in your application.

Example with Jackson:

```java
package <your-package>.enrichment;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

@Component
public class TransactionEventParser {

    private final ObjectMapper objectMapper;

    public TransactionEventParser(
            ObjectMapper objectMapper) {

        this.objectMapper = objectMapper;
    }

    public TransactionEvent parse(
            String payload) {

        try {

            JsonNode root =
                    objectMapper.readTree(payload);

            String transactionId =
                    root.at(
                        "/KafkaTransaction/transaction_id"
                    ).asText(null);

            String action =
                    root.at(
                        "/KafkaTransaction/action"
                    ).asText(null);

            if (transactionId == null ||
                action == null) {

                throw new IllegalArgumentException(
                        "transaction_id/action missing"
                );
            }

            return new TransactionEvent(
                    transactionId,
                    action,
                    payload
            );

        } catch (Exception e) {

            throw new IllegalArgumentException(
                    "Unable to parse transaction event",
                    e
            );
        }
    }
}
```

### TODO — only one thing here

Update the JSON paths to match your actual payload.

For example, if your actual JSON is:

```json
{
  "kafka": {
    "transaction": {
      "transaction_id": "123"
    }
  }
}
```

then change the path.

---

# 11. File 6 — `TransactionEnricher.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionEnricher.java
```

This is where you will put your actual enrichment logic.

```java
package <your-package>.enrichment;

import org.springframework.stereotype.Component;

@Component
public class TransactionEnricher {

    public String enrich(
            String currentPayload,
            String t1Payload) {

        /*
         * TODO:
         *
         * Your actual T1 → T2/T3/T4 enrichment logic.
         *
         * Return the updated JSON payload.
         */

        return currentPayload;
    }
}
```

This is intentionally the only business TODO.

---

# 12. File 7 — `TransactionEnrichmentProcessor.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionEnrichmentProcessor.java
```

This is the core stateful component.

```java
package <your-package>.enrichment;

import org.apache.kafka.streams.processor.api.ContextualProcessor;
import org.apache.kafka.streams.processor.api.ProcessorContext;
import org.apache.kafka.streams.processor.api.Record;
import org.apache.kafka.streams.state.KeyValueStore;

public class TransactionEnrichmentProcessor
        extends ContextualProcessor<
                String,
                TransactionEvent,
                String,
                TransactionEvent> {

    private final String stateStoreName;
    private final TransactionEnricher enricher;

    private KeyValueStore<
            String,
            TransactionState> stateStore;

    public TransactionEnrichmentProcessor(
            String stateStoreName,
            TransactionEnricher enricher) {

        this.stateStoreName = stateStoreName;
        this.enricher = enricher;
    }

    @SuppressWarnings("unchecked")
    @Override
    public void init(
            ProcessorContext<
                    String,
                    TransactionEvent> context) {

        super.init(context);

        stateStore =
                (KeyValueStore<
                        String,
                        TransactionState>)
                        context.getStateStore(
                                stateStoreName
                        );
    }

    @Override
    public void process(
            Record<String, TransactionEvent> record) {

        TransactionEvent event =
                record.value();

        String transactionId =
                event.getTransactionId();

        String action =
                event.getAction();

        /*
         * T1
         */
        if ("submit".equalsIgnoreCase(action)) {

            stateStore.put(
                    transactionId,
                    new TransactionState(
                            transactionId,
                            event.getPayload()
                    )
            );

            context().forward(record);

            return;
        }

        /*
         * T2/T3/T4/other event
         */
        TransactionState state =
                stateStore.get(transactionId);

        if (state == null) {

            /*
             * IMPORTANT:
             *
             * This is the rare T2-before-T1 case.
             *
             * Do not silently publish an incomplete event.
             *
             * The final production strategy for this case should
             * be agreed with the business/error-handling design.
             */
            throw new IllegalStateException(
                    "T1 state not found for transactionId="
                            + transactionId
            );
        }

        String enrichedPayload =
                enricher.enrich(
                        event.getPayload(),
                        state.getT1Payload()
                );

        TransactionEvent enrichedEvent =
                new TransactionEvent(
                        transactionId,
                        action,
                        enrichedPayload
                );

        context().forward(
                record.withValue(enrichedEvent)
        );

        /*
         * Terminal event.
         */
        if ("finished".equalsIgnoreCase(action)) {

            stateStore.delete(
                    transactionId
            );
        }
    }
}
```

---

# 13. File 8 — `TransactionEnrichmentTopology.java`

Path:

```text
src/main/java/<your-package>/enrichment/TransactionEnrichmentTopology.java
```

This is the starting point of the entire flow.

```java
package <your-package>.enrichment;

import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.KStream;
import org.apache.kafka.streams.kstream.Named;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.kstream.Repartitioned;
import org.apache.kafka.streams.processor.ProcessorContext;
import org.apache.kafka.streams.state.KeyValueBytesStoreSupplier;
import org.apache.kafka.streams.state.KeyValueStore;
import org.apache.kafka.streams.state.Stores;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class TransactionEnrichmentTopology {

    private static final String STATE_STORE =
            "transaction-t1-state";

    @Bean
    public KStream<String, TransactionEvent>
    transactionTopology(
            StreamsBuilder builder,
            TransactionEventParser parser,
            TransactionEnricher enricher,
            TransactionStateSerde stateSerde) {

        /*
         * 1. INPUT
         *
         * Input is String / String.
         */
        KStream<String, String> source =
                builder.stream(
                        "${transaction.input-topic}",
                        Consumed.with(
                                Serdes.String(),
                                Serdes.String()
                        )
                );

        /*
         * 2. Parse JSON once.
         */
        KStream<String, TransactionEvent> parsed =
                source.mapValues(
                        parser::parse
                );

        /*
         * 3. transaction_id is NOT the original Kafka key.
         *
         * Re-key using the transaction ID.
         */
        KStream<String, TransactionEvent> keyed =
                parsed.selectKey(
                        (oldKey, event) ->
                                event.getTransactionId()
                );

        /*
         * 4. Repartition.
         *
         * This ensures all events for one transaction are
         * processed by the same Kafka Streams task.
         */
        KStream<String, TransactionEvent> repartitioned =
                keyed.repartition(
                        Repartitioned
                                .with(
                                        Serdes.String(),
                                        transactionEventSerde()
                                )
                                .withName(
                                        "transaction-id-repartition"
                                )
                );

        /*
         * 5. State store.
         */
        builder.addStateStore(
                Stores.keyValueStoreBuilder(
                        Stores.persistentKeyValueStore(
                                STATE_STORE
                        ),
                        Serdes.String(),
                        stateSerde
                )
        );

        /*
         * 6. Stateful T1 enrichment.
         */
        KStream<String, TransactionEvent> enriched =
                repartitioned.process(
                        () ->
                                new TransactionEnrichmentProcessor(
                                        STATE_STORE,
                                        enricher
                                ),
                        Named.as(
                                "transaction-enrichment"
                        ),
                        STATE_STORE
                );

        /*
         * 7. Output conversion to GenericRecord
         *
         * This is intentionally left as an integration point
         * because your existing SchemaProvider already obtains
         * the schema from Schema Registry.
         */

        /*
         * TODO:
         *
         * KStream<String, GenericRecord> output =
         *     enriched.mapValues(
         *         event -> schemaProvider.toGenericRecord(
         *             event.getPayload()
         *         )
         *     );
         *
         * output.to(
         *     outputTopic,
         *     Produced.with(
         *         Serdes.String(),
         *         genericAvroSerde
         *     )
         * );
         */

        return enriched;
    }

    private Serde<TransactionEvent>
    transactionEventSerde() {

        /*
         * TODO:
         *
         * Add a small JSON SerDe for TransactionEvent.
         *
         * Alternatively, simplify the topology further and use
         * the parsed JSON representation already used by your app.
         */

        throw new UnsupportedOperationException(
                "Wire TransactionEvent Serde"
        );
    }
}
```

---

# 14. Important: do not copy the topology above blindly

There are only **two application-specific integration points**:

### Integration point 1 — your existing SchemaProvider

You already have something like:

```java
Schema schema =
        schemaProvider.getSchema(...);
```

Use that for the final:

```text
String/JSON
    ↓
GenericRecord
```

creation.

You do **not** need to create the Avro schema locally.

### Integration point 2 — JSON paths

Update:

```java
/KafkaTransaction/transaction_id
/KafkaTransaction/action
```

to match the actual input JSON.

---

# 15. How your existing SchemaProvider fits

The final output should be approximately:

```java
GenericRecord record =
        schemaProvider.createRecord(
                outputSchema,
                enrichedPayload
        );
```

The exact method depends on your existing class.

The important architecture is:

```text
Kafka input String
        ↓
Kafka Streams
        ↓
JSON enrichment
        ↓
your existing SchemaProvider
        ↓
Schema Registry schema
        ↓
GenericRecord
        ↓
KafkaAvroSerializer
        ↓
output topic
```

Do not create another schema loader.

---

# 16. What happens to `KafkaTemplate<String, GenericRecord>`?

You do not need to manually call it for the Kafka Streams output.

The old path:

```java
KafkaTemplate<String, GenericRecord>
        ↓
send(...)
        ↓
KafkaAvroSerializer
```

can remain for other application flows.

For the new Streams topology:

```text
KStream<String, GenericRecord>
        ↓
Produced.with(...)
        ↓
GenericAvroSerde
        ↓
KafkaAvroSerializer
        ↓
Kafka
```

The underlying serializer is still Kafka Avro serialization.

---

# 17. What happens to the DLQ?

Your DLQ is:

```text
String / String
```

So keep:

```java
KafkaTemplate<String, String>
```

and send a JSON error string.

Example:

```java
dlqProducer.send(
        dlqTopic,
        transactionId,
        errorJson
);
```

No Avro schema is needed for the DLQ.

---

# 18. What happens to `AsyncProcessingService`?

Do not make Kafka Streams call:

```java
@Async
```

The flow should become:

```text
Kafka Streams
      ↓
TransactionEnrichmentProcessor
      ↓
existing synchronous transformation methods
      ↓
GenericRecord
      ↓
Kafka output
```

If `AsyncProcessingService` currently contains both:

```text
@Async infrastructure
+
business transformation
```

extract only the business transformation into a normal service.

For example:

```java
@Component
public class TransactionTransformationService {

    public String transform(
            String enrichedPayload) {

        /*
         * Move existing business transformation here.
         */

        return enrichedPayload;
    }
}
```

Then the processor/topology calls it synchronously.

---

# 19. One important production issue still remaining

There is one case we have intentionally not hidden:

```text
T2 arrives
   ↓
T1 not yet available
```

We know T1 normally arrives first, but you said it can very rarely happen in reverse.

Do not solve this with:

```java
Thread.sleep()
```

or:

```java
ConcurrentHashMap
```

The correct production solution is durable pending-event handling.

We can add that after the core T1 → subsequent-event flow is working.

---

# 20. 90-day retention

Do not keep 10,000 transactions in JVM memory for 90 days.

The state store is disk-backed and Kafka-backed.

Normal lifecycle:

```text
T1
 ↓
state store
 ↓
T2/T3/T4...
 ↓
finished
 ↓
delete
```

The 90-day value is a safety/expiry boundary for transactions that never receive `finished`.

That stale-state cleanup should be configured separately from the normal terminal-event deletion.

---

# 21. Final implementation order

Implement in this exact conceptual order:

```text
1. KafkaStreamsConfig
       ↓
2. Input KStream<String,String>
       ↓
3. TransactionEventParser
       ↓
4. TransactionEvent
       ↓
5. selectKey(transaction_id)
       ↓
6. repartition
       ↓
7. TransactionState
       ↓
8. TransactionStateSerde
       ↓
9. State store
       ↓
10. TransactionEnricher
       ↓
11. TransactionEnrichmentProcessor
       ↓
12. Existing transformation logic
       ↓
13. Existing SchemaProvider
       ↓
14. GenericRecord
       ↓
15. GenericAvroSerde / KafkaAvroSerializer
       ↓
16. Output topic
```

Error path:

```text
Any unrecoverable processing error
       ↓
KafkaTemplate<String,String>
       ↓
DLQ
```

---

# 22. What you actually need to fill in

There should be only these application-specific pieces:

### 1. Input JSON field paths

```java
transaction_id
action
```

### 2. `TransactionEnricher`

Your actual T1 → current-event field enrichment.

### 3. Existing SchemaProvider call

Use your existing schema loader/provider.

### 4. GenericRecord creation

Use the schema returned by your existing SchemaProvider.

### 5. Existing business transformation

Move/reuse it from `AsyncProcessingService`.

### 6. Existing Kafka/Schema Registry configuration

Reuse it rather than duplicating configuration.

### 7. T2-before-T1 policy

Implement durable pending-event handling after the basic flow is working.

---

# 23. Final architecture

```text
INPUT TOPIC
String / String
       │
       ▼
KStream<String,String>
       │
       ▼
JSON parser
       │
       ▼
TransactionEvent
       │
       ▼
transaction_id
       │
       ▼
selectKey(transaction_id)
       │
       ▼
repartition
       │
       ▼
STATE STORE
transaction_id → T1 JSON
       │
       ├──────── T1/submit ───────→ store
       │
       ├──────── T2/T3/... ───────→ lookup T1
       │                              │
       │                              ▼
       │                           enrich
       │
       └──────── finished ────────→ lookup T1
                                      │
                                      ▼
                                    enrich
                                      │
                                      ▼
                                  delete state
                                      │
                                      ▼
                           Existing transformation
                                      │
                                      ▼
                            Existing SchemaProvider
                                      │
                                      ▼
                                GenericRecord
                                      │
                                      ▼
                           KafkaAvroSerializer
                                      │
                                      ▼
OUTPUT / RESTRICTED / TARGETED TOPIC
String / GenericRecord


ERROR
  │
  ▼
KafkaTemplate<String,String>
  │
  ▼
DLQ
String / String
```

This is the simplified implementation direction to use going forward. Do not use the earlier `GenericRecord` input/state-store model.
