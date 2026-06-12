package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import com.uptimecrew.expense.entity.Merchant;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.repository.MerchantRepository;

@ExtendWith(MockitoExtension.class)
class ExpenseClassificationServiceMockitoTest {

    @Mock
    private TransactionClassifier classifier;

    @Mock
    private MerchantRepository merchantRepository;

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

        ExpenseClassificationService subject =
                new ExpenseClassificationService(classifier, merchantRepository);

        TransactionKind result = subject.classify(transaction);

        assertEquals(TransactionKind.DEDUCTIBLE, result);
        verify(classifier).classify(transaction);
        verify(merchantRepository).save(any(Merchant.class));
    }
}
