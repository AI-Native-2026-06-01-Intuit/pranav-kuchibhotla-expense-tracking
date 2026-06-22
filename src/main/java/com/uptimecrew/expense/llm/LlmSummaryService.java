package com.uptimecrew.expense.llm;

import java.util.Objects;

import org.springframework.stereotype.Service;

import com.uptimecrew.expense.graphql.MerchantSummary;

// Task 3 will wire Spring AI ChatClient + structured output + JSON Schema
// validation. For Task 1 this returns a deterministic placeholder so the
// GraphQL mutation resolves and the context loads.
@Service
public class LlmSummaryService {

    public MerchantSummary summarize(String id) {
        Objects.requireNonNull(id, "id");
        return new MerchantSummary("UNKNOWN", 0.0, 0, "UNKNOWN");
    }
}
