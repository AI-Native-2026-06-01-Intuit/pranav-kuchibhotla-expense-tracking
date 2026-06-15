package com.uptimecrew.expense.service;

import java.util.Locale;
import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.exception.ExpenseClassificationException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.repository.MerchantRepository;

/**
 * Service that classifies expenses by delegating to an injected transaction classifier.
 */
@Service
public class ExpenseClassificationService {

    private static final Logger LOG = LoggerFactory.getLogger(ExpenseClassificationService.class);

    private final TransactionClassifier classifier;
    private final MerchantRepository merchantRepository;

    public ExpenseClassificationService(TransactionClassifier classifier,
                                        MerchantRepository merchantRepository) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
        this.merchantRepository = Objects.requireNonNull(merchantRepository, "merchantRepository must not be null");
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

    private static Merchant buildMerchantFrom(Transaction transaction) {
        String normalizedName = transaction.merchantName().trim().toLowerCase(Locale.ROOT);
        String id = "merchant-" + normalizedName;
        return new Merchant(id, transaction.merchantName(), normalizedName, "UNKNOWN");
    }
}
