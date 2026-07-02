package com.uptimecrew.expense.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class RecurringChargeClassifierTest {

    @Test
    @DisplayName("classify_monthlyStableHistory_returnsDeductible")
    void classify_monthlyStableHistory_returnsDeductible() {
        // Arrange
        Transaction jan = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 10));
        Transaction feb = new Transaction(
                "t-2", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 2, 9));
        Transaction mar = new Transaction(
                "t-3", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 3, 11));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(jan, feb));

        // Act
        TransactionKind kind = classifier.classify(mar);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.DEDUCTIBLE);
    }

    @Test
    @DisplayName("classify_insufficientMerchantHistory_returnsNonDeductible")
    void classify_insufficientMerchantHistory_returnsNonDeductible() {
        // Arrange
        Transaction onlyPrior = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 10));
        Transaction current = new Transaction(
                "t-2", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 2, 9));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(onlyPrior));

        // Act
        TransactionKind kind = classifier.classify(current);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.NON_DEDUCTIBLE);
    }

    @Test
    @DisplayName("classify_amountDiffers_returnsNonDeductible")
    void classify_amountDiffers_returnsNonDeductible() {
        // Arrange
        Transaction jan = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 10));
        Transaction feb = new Transaction(
                "t-2", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 2, 9));
        Transaction mar = new Transaction(
                "t-3", "acct-1", new BigDecimal("14.99"), "Netflix", LocalDate.of(2026, 3, 11));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(jan, feb));

        // Act
        TransactionKind kind = classifier.classify(mar);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.NON_DEDUCTIBLE);
    }

    @Test
    @DisplayName("constructor_nullHistory_throwsNullPointerException")
    void constructor_nullHistory_throwsNullPointerException() {
        // Arrange
        List<Transaction> history = null;

        // Act + Assert
        assertThatThrownBy(() -> new RecurringChargeClassifier(history))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    @DisplayName("classify_nonMonthlyCadence_returnsNonDeductible")
    void classify_nonMonthlyCadence_returnsNonDeductible() {
        // Arrange
        Transaction jan = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 1));
        Transaction feb = new Transaction(
                "t-2", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 2, 20));
        Transaction current = new Transaction(
                "t-3", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 3, 22));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(jan, feb));

        // Act
        TransactionKind kind = classifier.classify(current);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.NON_DEDUCTIBLE);
    }

    @Test
    @DisplayName("classify_nullTransaction_throwsNullPointerException")
    void classify_nullTransaction_throwsNullPointerException() {
        // Arrange
        Transaction prior = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 10));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(prior));

        // Act + Assert
        assertThatThrownBy(() -> classifier.classify(null))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    @DisplayName("classify_shortCadence_returnsNonDeductible")
    void classify_shortCadence_returnsNonDeductible() {
        // Arrange
        Transaction jan = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 1));
        Transaction janLate = new Transaction(
                "t-2", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 1, 21));
        Transaction current = new Transaction(
                "t-3", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 2, 15));
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of(jan, janLate));

        // Act
        TransactionKind kind = classifier.classify(current);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.NON_DEDUCTIBLE);
    }

    @Test
    @DisplayName("classify_emptyHistory_returnsNonDeductible")
    void classify_emptyHistory_returnsNonDeductible() {
        // Arrange
        RecurringChargeClassifier classifier = new RecurringChargeClassifier(List.of());
        Transaction current = new Transaction(
                "t-1", "acct-1", new BigDecimal("9.99"), "Netflix", LocalDate.of(2026, 3, 1));

        // Act
        TransactionKind kind = classifier.classify(current);

        // Assert
        assertThat(kind).isEqualTo(TransactionKind.NON_DEDUCTIBLE);
    }
}
