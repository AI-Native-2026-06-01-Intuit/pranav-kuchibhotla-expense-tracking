package com.uptimecrew.expense.model;

import java.time.Instant;
import java.util.Objects;

public final class Receipt {

    private final String id;
    private final String transactionId;
    private final String imageRef;
    private final Instant capturedAt;

    public Receipt(String id, String transactionId, String imageRef, Instant capturedAt) {
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(transactionId, "transactionId");
        Objects.requireNonNull(imageRef, "imageRef");
        Objects.requireNonNull(capturedAt, "capturedAt");
        if (id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (transactionId.isBlank()) {
            throw new IllegalArgumentException("transactionId must not be blank");
        }
        if (imageRef.isBlank()) {
            throw new IllegalArgumentException("imageRef must not be blank");
        }
        this.id = id;
        this.transactionId = transactionId;
        this.imageRef = imageRef;
        this.capturedAt = capturedAt;
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
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Receipt other)) return false;
        return id.equals(other.id)
                && transactionId.equals(other.transactionId)
                && imageRef.equals(other.imageRef)
                && capturedAt.equals(other.capturedAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, transactionId, imageRef, capturedAt);
    }

    @Override
    public String toString() {
        return "Receipt{id=" + id
                + ", transactionId=" + transactionId
                + ", imageRef=" + imageRef
                + ", capturedAt=" + capturedAt
                + '}';
    }
}
