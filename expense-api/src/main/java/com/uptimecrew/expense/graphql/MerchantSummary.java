package com.uptimecrew.expense.graphql;

public record MerchantSummary(
        String mccCode,
        Double totalSpend,
        Integer transactionCount,
        String primaryCategory) {
}
