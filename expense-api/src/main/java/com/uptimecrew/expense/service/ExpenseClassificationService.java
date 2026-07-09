package com.uptimecrew.expense.service;

import java.util.EnumMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.opentelemetry.instrumentation.annotations.WithSpan;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.consumer.MerchantClassifiedEvent;
import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.entity.MerchantTransaction;
import com.uptimecrew.expense.exception.ExpenseClassificationException;
import com.uptimecrew.expense.graphql.LineItem;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.outbox.EventOutboxEntity;
import com.uptimecrew.expense.outbox.EventOutboxRepository;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModel.EmbeddedTransaction;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.repository.MerchantRepository;

/**
 * Service that classifies expenses by delegating to an injected transaction classifier.
 */
@Service
public class ExpenseClassificationService {

    public static final String CACHE_NAME = "expense.byId";
    public static final String DEDUCTIONS_COUNTER_NAME = "expense_deductions_identified_total";
    private static final String MERCHANTS_TOPIC = "merchants.events";

    private static final Logger LOG = LoggerFactory.getLogger(ExpenseClassificationService.class);

    // Bounded label values keep the metric cardinality fixed at 3 x 3 = 9 series.
    // Adding merchantId/userId/correlationId here would blow up Prometheus.
    enum MerchantType { synthetic, known, unknown }
    enum Outcome { success, not_found, error }

    private final TransactionClassifier classifier;
    private final MerchantRepository merchantRepository;
    private final MerchantReadModelRepository merchantReadModelRepository;
    private final EventOutboxRepository eventOutboxRepository;
    private final ObjectMapper objectMapper;
    private final Map<MerchantType, Map<Outcome, Counter>> deductionCounters;

    public ExpenseClassificationService(TransactionClassifier classifier,
                                        MerchantRepository merchantRepository,
                                        MerchantReadModelRepository merchantReadModelRepository,
                                        EventOutboxRepository eventOutboxRepository,
                                        ObjectMapper objectMapper,
                                        MeterRegistry meterRegistry) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
        this.merchantRepository = Objects.requireNonNull(merchantRepository, "merchantRepository must not be null");
        this.merchantReadModelRepository = Objects.requireNonNull(
                merchantReadModelRepository, "merchantReadModelRepository must not be null");
        this.eventOutboxRepository = Objects.requireNonNull(
                eventOutboxRepository, "eventOutboxRepository must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        Objects.requireNonNull(meterRegistry, "meterRegistry must not be null");
        this.deductionCounters = new EnumMap<>(MerchantType.class);
        for (MerchantType mt : MerchantType.values()) {
            Map<Outcome, Counter> byOutcome = new EnumMap<>(Outcome.class);
            for (Outcome oc : Outcome.values()) {
                byOutcome.put(oc, Counter.builder(DEDUCTIONS_COUNTER_NAME)
                        .description("Merchant lookups classified as candidate deductions.")
                        .tag("merchant_type", mt.name())
                        .tag("outcome", oc.name())
                        .register(meterRegistry));
            }
            deductionCounters.put(mt, byOutcome);
        }
    }

    private static MerchantType classifyMerchantType(String id) {
        if (id == null) {
            return MerchantType.unknown;
        }
        if (id.startsWith("mer_synth_")) {
            return MerchantType.synthetic;
        }
        if (id.startsWith("merchant-")) {
            return MerchantType.known;
        }
        return MerchantType.unknown;
    }

    @Transactional
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        LOG.info("classifying transaction id={} merchant={}",
                transaction.id(), transaction.merchantName());
        try {
            TransactionKind kind = classifier.classify(transaction);
            LOG.info("classified transaction id={} as kind={}", transaction.id(), kind);

            Merchant saved = merchantRepository.save(buildMerchantFrom(transaction));
            LOG.info("persisted merchant id={}", saved.getId());

            MerchantReadModel projection = toReadModel(saved, deriveMccCode(saved, kind));
            merchantReadModelRepository.save(projection);
            LOG.info("wrote merchant read model id={} mccCode={}",
                    projection.getId(), projection.getMccCode());

            MerchantClassifiedEvent event = new MerchantClassifiedEvent(
                    saved.getId(),
                    saved.getDisplayName(),
                    saved.getNormalizedName(),
                    projection.getMccCode(),
                    kind.name());
            String payload;
            try {
                payload = objectMapper.writeValueAsString(event);
            } catch (JsonProcessingException ex) {
                throw new IllegalStateException(
                        "failed to serialize MerchantClassifiedEvent for outbox", ex);
            }
            eventOutboxRepository.save(
                    new EventOutboxEntity(saved.getId(), MERCHANTS_TOPIC, payload));
            LOG.info("wrote outbox row aggregateId={} topic={}", saved.getId(), MERCHANTS_TOPIC);

            return kind;
        } catch (ExpenseClassificationException ex) {
            LOG.warn("strategy failed: {}", ex.getMessage(), ex);
            throw ex;
        }
    }

    @WithSpan("merchant.findById")
    @Cacheable(value = CACHE_NAME, unless = "#result == null")
    @Transactional(readOnly = true)
    public Optional<MerchantReadModel> findById(String id) {
        Objects.requireNonNull(id, "id");

        MerchantType merchantType = classifyMerchantType(id);
        try {
            LOG.info("cache miss for id={}, reading from Mongo", id);
            Optional<MerchantReadModel> fromMongo = merchantReadModelRepository.findById(id);
            if (fromMongo.isPresent()) {
                deductionCounters.get(merchantType).get(Outcome.success).increment();
                return fromMongo;
            }

            LOG.info("Mongo miss for id={}, falling back to JPA", id);
            Optional<MerchantReadModel> fromJpa = merchantRepository.findById(id)
                    .map(m -> toReadModel(m, deriveMccCode(m, null)));
            Outcome outcome = fromJpa.isPresent() ? Outcome.success : Outcome.not_found;
            deductionCounters.get(merchantType).get(outcome).increment();
            return fromJpa;
        } catch (RuntimeException ex) {
            deductionCounters.get(merchantType).get(Outcome.error).increment();
            throw ex;
        }
    }

    @Transactional(readOnly = true)
    public List<MerchantReadModel> findLatest(int limit) {
        if (limit <= 0) {
            return List.of();
        }
        LOG.info("loading latest merchants limit={}", limit);
        return merchantReadModelRepository
                .findAllByOrderByCreatedAtDesc(PageRequest.of(0, limit));
    }

    // Batch loader for GraphQL Merchant.lines. The Mongo read model already
    // embeds the merchant's transactions, so this resolves all parents from
    // in-memory state in a single pass — no per-parent query, no N+1.
    public Map<MerchantReadModel, List<LineItem>> loadLineItemsByParent(
            List<MerchantReadModel> parents) {
        Objects.requireNonNull(parents, "parents");
        LOG.info("batch loading line items for {} merchant(s)", parents.size());
        Map<MerchantReadModel, List<LineItem>> result = new LinkedHashMap<>(parents.size());
        for (MerchantReadModel parent : parents) {
            List<EmbeddedTransaction> txs = parent.getTransactions();
            List<LineItem> lines = txs.isEmpty()
                    ? List.of()
                    : txs.stream().map(ExpenseClassificationService::toLineItem).toList();
            result.put(parent, lines);
        }
        return result;
    }

    private static LineItem toLineItem(EmbeddedTransaction tx) {
        String description = tx.getTransactionKind() != null
                ? tx.getTransactionKind()
                : "transaction";
        double amount = tx.getAmount() != null ? tx.getAmount().doubleValue() : 0.0;
        return new LineItem(tx.getId(), description, amount);
    }

    private static Merchant buildMerchantFrom(Transaction transaction) {
        String normalizedName = transaction.merchantName().trim().toLowerCase(Locale.ROOT);
        String id = "merchant-" + normalizedName;
        return new Merchant(id, transaction.merchantName(), normalizedName, "UNKNOWN");
    }

    private MerchantReadModel toReadModel(Merchant merchant, String mccCode) {
        List<MerchantTransaction> txs = merchant.getTransactions();
        List<EmbeddedTransaction> embedded = txs.isEmpty()
                ? List.of()
                : txs.stream()
                        .map(t -> new EmbeddedTransaction(
                                t.getId(),
                                t.getAccountId(),
                                t.getAmount(),
                                t.getTransactionKind(),
                                t.getOccurredAt(),
                                t.getClassifiedAt()))
                        .toList();
        return new MerchantReadModel(
                merchant.getId(),
                merchant.getDisplayName(),
                merchant.getNormalizedName(),
                merchant.getMerchantKind(),
                mccCode,
                merchant.getCreatedAt(),
                embedded);
    }

    // The W2D1 JPA schema has no merchant.mcc_code column and the current
    // TransactionClassifier returns only a TransactionKind (no MCC). The W2D5
    // read-model spec still requires an indexed mccCode on the Mongo document,
    // so we derive it from normalizedName as a documented fallback until a
    // real MCC signal is added upstream. Kept here so the Mongo document
    // always has a non-null mccCode and the @Indexed annotation is meaningful.
    private static String deriveMccCode(Merchant merchant, TransactionKind kind) {
        return merchant.getNormalizedName();
    }
}
