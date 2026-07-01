package com.uptimecrew.expense.consumer;

/**
 * Kafka contract payload emitted when a merchant has been classified.
 * Carries everything the read-model consumer needs to rebuild a
 * {@code MerchantReadModel} without touching the primary store.
 */
public record MerchantClassifiedEvent(
        String aggregateId,
        String displayName,
        String normalizedName,
        String mccCode,
        String classificationKind) {
}
