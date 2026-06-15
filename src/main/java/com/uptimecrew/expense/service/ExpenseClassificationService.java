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

import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.entity.MerchantTransaction;
import com.uptimecrew.expense.exception.ExpenseClassificationException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
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

    private static final Logger LOG = LoggerFactory.getLogger(ExpenseClassificationService.class);

    private final TransactionClassifier classifier;
    private final MerchantRepository merchantRepository;
    private final MerchantReadModelRepository merchantReadModelRepository;

    public ExpenseClassificationService(TransactionClassifier classifier,
                                        MerchantRepository merchantRepository,
                                        MerchantReadModelRepository merchantReadModelRepository) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
        this.merchantRepository = Objects.requireNonNull(merchantRepository, "merchantRepository must not be null");
        this.merchantReadModelRepository = Objects.requireNonNull(
                merchantReadModelRepository, "merchantReadModelRepository must not be null");
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

            return kind;
        } catch (ExpenseClassificationException ex) {
            LOG.warn("strategy failed: {}", ex.getMessage(), ex);
            throw ex;
        }
    }

    @Cacheable(value = CACHE_NAME, unless = "#result == null || #result.isEmpty()")
    @Transactional(readOnly = true)
    public Optional<MerchantReadModel> findById(String id) {
        Objects.requireNonNull(id, "id");

        LOG.info("cache miss for id={}, reading from Mongo", id);
        Optional<MerchantReadModel> fromMongo = merchantReadModelRepository.findById(id);
        if (fromMongo.isPresent()) {
            return fromMongo;
        }

        LOG.info("Mongo miss for id={}, falling back to JPA", id);
        return merchantRepository.findById(id).map(this::toReadModel);
    }

    private static Merchant buildMerchantFrom(Transaction transaction) {
        String normalizedName = transaction.merchantName().trim().toLowerCase(Locale.ROOT);
        String id = "merchant-" + normalizedName;
        return new Merchant(id, transaction.merchantName(), normalizedName, "UNKNOWN");
    }

    private MerchantReadModel toReadModel(Merchant merchant) {
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
                merchant.getCreatedAt(),
                embedded);
    }
}
