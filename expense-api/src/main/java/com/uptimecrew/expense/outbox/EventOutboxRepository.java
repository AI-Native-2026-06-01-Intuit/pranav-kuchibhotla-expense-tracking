package com.uptimecrew.expense.outbox;

import java.util.List;
import java.util.UUID;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface EventOutboxRepository extends JpaRepository<EventOutboxEntity, UUID> {

    // FOR UPDATE SKIP LOCKED: multiple publisher instances can poll the same
    // table concurrently without blocking each other and without two of them
    // grabbing the same row — Postgres skips rows already locked by another
    // transaction, eliminating the double-publish race.
    @Query(value = """
            SELECT *
            FROM expense.event_outbox
            WHERE published_at IS NULL
            ORDER BY occurred_at
            FOR UPDATE SKIP LOCKED
            """, nativeQuery = true)
    List<EventOutboxEntity> findUnpublishedForUpdate(Pageable pageable);
}
