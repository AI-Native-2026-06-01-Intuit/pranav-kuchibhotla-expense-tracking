package com.uptimecrew.expense.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.outbox.EventOutboxRepository;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.repository.MerchantRepository;

@ExtendWith(MockitoExtension.class)
class ExpenseClassificationServiceMockitoTest {

    @Mock
    private TransactionClassifier classifier;

    @Mock
    private MerchantRepository merchantRepository;

    @Mock
    private MerchantReadModelRepository merchantReadModelRepository;

    @Mock
    private EventOutboxRepository eventOutboxRepository;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void classify_validTransaction_delegatesToInjectedClassifier() {
        Transaction transaction = new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1));

        when(classifier.classify(any(Transaction.class)))
                .thenReturn(TransactionKind.DEDUCTIBLE);
        when(merchantRepository.save(any(Merchant.class)))
                .thenAnswer(inv -> inv.getArgument(0));
        when(merchantReadModelRepository.save(any(MerchantReadModel.class)))
                .thenAnswer(inv -> inv.getArgument(0));

        ExpenseClassificationService subject =
                new ExpenseClassificationService(
                        classifier, merchantRepository, merchantReadModelRepository,
                        eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        TransactionKind result = subject.classify(transaction);

        assertEquals(TransactionKind.DEDUCTIBLE, result);
        verify(classifier).classify(transaction);
        verify(merchantRepository).save(any(Merchant.class));
        ArgumentCaptor<MerchantReadModel> captor = ArgumentCaptor.forClass(MerchantReadModel.class);
        verify(merchantReadModelRepository).save(captor.capture());
        assertThat(captor.getValue().getMccCode()).isEqualTo("office depot");
    }

    @Test
    void findById_mongoHit_returnsReadModel() {
        MerchantReadModel doc = new MerchantReadModel(
                "merchant-office depot",
                "Office Depot",
                "office depot",
                "UNKNOWN",
                "office depot",
                null,
                List.of());
        when(merchantReadModelRepository.findById("merchant-office depot"))
                .thenReturn(Optional.of(doc));

        ExpenseClassificationService subject = new ExpenseClassificationService(
                classifier, merchantRepository, merchantReadModelRepository,
                eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        Optional<MerchantReadModel> result = subject.findById("merchant-office depot");

        assertThat(result).containsSame(doc);
        verify(merchantRepository, never()).findById(any());
    }

    @Test
    void findById_mongoMissFallsBackToJpa_returnsProjection() {
        when(merchantReadModelRepository.findById("merchant-office depot"))
                .thenReturn(Optional.empty());
        Merchant jpaMerchant = new Merchant(
                "merchant-office depot", "Office Depot", "office depot", "UNKNOWN");
        when(merchantRepository.findById("merchant-office depot"))
                .thenReturn(Optional.of(jpaMerchant));

        ExpenseClassificationService subject = new ExpenseClassificationService(
                classifier, merchantRepository, merchantReadModelRepository,
                eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        Optional<MerchantReadModel> result = subject.findById("merchant-office depot");

        assertThat(result).isPresent();
        assertThat(result.get().getId()).isEqualTo("merchant-office depot");
        assertThat(result.get().getDisplayName()).isEqualTo("Office Depot");
        assertThat(result.get().getNormalizedName()).isEqualTo("office depot");
        assertThat(result.get().getMerchantKind()).isEqualTo("UNKNOWN");
        assertThat(result.get().getMccCode()).isEqualTo("office depot");
        assertThat(result.get().getTransactions()).isEmpty();
    }

    @Test
    void findById_notFound_returnsEmpty() {
        when(merchantReadModelRepository.findById("missing"))
                .thenReturn(Optional.empty());
        when(merchantRepository.findById("missing"))
                .thenReturn(Optional.empty());

        ExpenseClassificationService subject = new ExpenseClassificationService(
                classifier, merchantRepository, merchantReadModelRepository,
                eventOutboxRepository, objectMapper, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());

        assertThat(subject.findById("missing")).isEmpty();
    }
}
