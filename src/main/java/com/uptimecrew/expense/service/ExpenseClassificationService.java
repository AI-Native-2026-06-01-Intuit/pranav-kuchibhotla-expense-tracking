package com.uptimecrew.expense.service;

import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.consumer.MerchantClassifiedEvent;
import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.entity.MerchantTransaction;
import com.uptimecrew.expense.exception.ExpenseClassificationException;
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
    private static final String MERCHANTS_TOPIC = "merchants.events";

    private static final Logger LOG = LoggerFactory.getLogger(ExpenseClassificationService.class);

    private final TransactionClassifier classifier;
    private final MerchantRepository merchantRepository;
    private final MerchantReadModelRepository merchantReadModelRepository;
    private final EventOutboxRepository eventOutboxRepository;
    private final ObjectMapper objectMapper;

    public ExpenseClassificationService(TransactionClassifier classifier,
                                        MerchantRepository merchantRepository,
                                        MerchantReadModelRepository merchantReadModelRepository,
                                        EventOutboxRepository eventOutboxRepository,
                                        ObjectMapper objectMapper) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
        this.merchantRepository = Objects.requireNonNull(merchantRepository, "merchantRepository must not be null");
        this.merchantReadModelRepository = Objects.requireNonNull(
                merchantReadModelRepository, "merchantReadModelRepository must not be null");
        this.eventOutboxRepository = Objects.requireNonNull(
                eventOutboxRepository, "eventOutboxRepository must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
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

    @Cacheable(value = CACHE_NAME, unless = "#result == null")
    @Transactional(readOnly = true)
    public Optional<MerchantReadModel> findById(String id) {
        Objects.requireNonNull(id, "id");

        LOG.info("cache miss for id={}, reading from Mongo", id);
        Optional<MerchantReadModel> fromMongo = merchantReadModelRepository.findById(id);
        if (fromMongo.isPresent()) {
            return fromMongo;
        }

        LOG.info("Mongo miss for id={}, falling back to JPA", id);
        return merchantRepository.findById(id)
                .map(m -> toReadModel(m, deriveMccCode(m, null)));
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
