package com.uptimecrew.expense.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.exception.TransactionParseException;
import com.uptimecrew.expense.exception.UnrecognizedMerchantException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.outbox.EventOutboxRepository;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.repository.MerchantRepository;

@ExtendWith(MockitoExtension.class)
class ExpenseClassificationServiceExceptionPathTest {

    @Mock
    private TransactionClassifier classifier;

    @Mock
    private MerchantRepository merchantRepository;

    @Mock
    private MerchantReadModelRepository merchantReadModelRepository;

    @Mock
    private EventOutboxRepository eventOutboxRepository;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private Logger serviceLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void attachAppender() {
        serviceLogger = (Logger) LoggerFactory.getLogger(ExpenseClassificationService.class);
        appender = new ListAppender<>();
        appender.start();
        serviceLogger.addAppender(appender);
    }

    @AfterEach
    void detachAppender() {
        serviceLogger.detachAppender(appender);
        appender.stop();
    }

    @Test
    void classify_unrecognizedMerchant_throwsTypedException() {
        when(classifier.classify(any(Transaction.class)))
                .thenThrow(new UnrecognizedMerchantException("unrecognized merchant: "));

        ExpenseClassificationService subject =
                new ExpenseClassificationService(
                        classifier, merchantRepository, merchantReadModelRepository,
                        eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        assertThatThrownBy(() -> subject.classify(validTransaction()))
                .isInstanceOf(UnrecognizedMerchantException.class)
                .hasMessageContaining("unrecognized merchant");

        verify(merchantRepository, never()).save(any(Merchant.class));
        verify(merchantReadModelRepository, never()).save(any(MerchantReadModel.class));
    }

    @Test
    void classify_parseFailure_preservesRootCause() {
        IOException cause = new IOException("synthetic parse failure");
        when(classifier.classify(any(Transaction.class)))
                .thenThrow(new TransactionParseException("failed parsing transaction row", cause));

        ExpenseClassificationService subject =
                new ExpenseClassificationService(
                        classifier, merchantRepository, merchantReadModelRepository,
                        eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        assertThatThrownBy(() -> subject.classify(validTransaction()))
                .isInstanceOf(TransactionParseException.class)
                .hasRootCauseInstanceOf(IOException.class);

        verify(merchantRepository, never()).save(any(Merchant.class));
        verify(merchantReadModelRepository, never()).save(any(MerchantReadModel.class));
    }

    @Test
    void classify_domainFailure_emitsWarnLogLine() {
        when(classifier.classify(any(Transaction.class)))
                .thenThrow(new UnrecognizedMerchantException("unrecognized merchant: Office Depot"));

        ExpenseClassificationService subject =
                new ExpenseClassificationService(
                        classifier, merchantRepository, merchantReadModelRepository,
                        eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        assertThatThrownBy(() -> subject.classify(validTransaction()))
                .isInstanceOf(UnrecognizedMerchantException.class);

        assertThat(appender.list)
                .filteredOn(event -> event.getLevel() == Level.WARN)
                .singleElement()
                .satisfies(event -> assertThat(event.getFormattedMessage())
                        .contains("unrecognized merchant: Office Depot"));

        verify(merchantRepository, never()).save(any(Merchant.class));
        verify(merchantReadModelRepository, never()).save(any(MerchantReadModel.class));
    }

    private Transaction validTransaction() {
        return new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1)
        );
    }
}
