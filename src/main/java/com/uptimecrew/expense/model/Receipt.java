package com.uptimecrew.expense.model;

import java.time.Instant;
import java.util.Objects;

/**
 * A captured receipt image attached to a {@link Transaction}, identified by
 * an external image reference and the instant it was captured.
 */
public final class Receipt {

    private final String id;
    private final String transactionId;
    private final String imageRef;
    private final Instant capturedAt;

    public Receipt(String id, String transactionId, String imageRef, Instant capturedAt) {
        this.id = requireNonBlank(id, "id");
        this.transactionId = requireNonBlank(transactionId, "transactionId");
        this.imageRef = requireNonBlank(imageRef, "imageRef");
        this.capturedAt = Objects.requireNonNull(capturedAt, "capturedAt must not be null");
    }

    private static String requireNonBlank(String value, String fieldName) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must be non-blank");
        }
        return value;
    }

    public String id() {
        return id;
    }

    public String transactionId() {
        return transactionId;
    }

    public String imageRef() {
        return imageRef;
    }

    public Instant capturedAt() {
        return capturedAt;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Receipt that)) {
            return false;
        }
        return id.equals(that.id)
                && transactionId.equals(that.transactionId)
                && imageRef.equals(that.imageRef)
                && capturedAt.equals(that.capturedAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, transactionId, imageRef, capturedAt);
    }

    @Override
    public String toString() {
        return "Receipt{"
                + "id='" + id + '\''
                + ", transactionId='" + transactionId + '\''
                + ", imageRef='" + imageRef + '\''
                + ", capturedAt=" + capturedAt
                + '}';
    }
}
