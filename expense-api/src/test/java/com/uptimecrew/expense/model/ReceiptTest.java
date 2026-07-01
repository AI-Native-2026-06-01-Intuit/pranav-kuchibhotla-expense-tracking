package com.uptimecrew.expense.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Instant;

import org.junit.jupiter.api.Test;

class ReceiptTest {

    @Test
    void constructor_validInputs_setsFields() {
        Instant capturedAt = Instant.parse("2026-03-01T12:00:00Z");

        Receipt subject = new Receipt(
                "rcpt-synth-001",
                "txn-synth-001",
                "s3://receipts/rcpt-synth-001.png",
                capturedAt);

        assertEquals("rcpt-synth-001", subject.id());
        assertEquals("txn-synth-001", subject.transactionId());
        assertEquals("s3://receipts/rcpt-synth-001.png", subject.imageRef());
        assertEquals(capturedAt, subject.capturedAt());
    }

    @Test
    void constructor_nullCapturedAt_throwsNullPointerException() {
        assertThrows(NullPointerException.class, () -> new Receipt(
                "rcpt-synth-001",
                "txn-synth-001",
                "s3://receipts/rcpt-synth-001.png",
                null));
    }

    @Test
    void constructor_blankImageRef_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class, () -> new Receipt(
                "rcpt-synth-001",
                "txn-synth-001",
                "",
                Instant.parse("2026-03-01T12:00:00Z")));
    }
}
