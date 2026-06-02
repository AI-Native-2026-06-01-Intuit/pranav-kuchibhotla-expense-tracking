// path: src/main/java/com/uptimecrew/expense/model/TransactionDraft.java
package com.uptimecrew.expense.model;

import java.util.Date;

// This class violates several conventions you just wrote into CLAUDE.md.
// Find the violations. Fix this file so all four TransactionDraftTest tests pass.
public class TransactionDraft {

    public long id;
    public double amount;
    public String merchantName;
    public Date occurredOn;

    public TransactionDraft(long id, double amount, String merchantName, Date occurredOn) {
        this.id = id;
        this.amount = amount;
        this.merchantName = merchantName;
        this.occurredOn = occurredOn;
    }
}
