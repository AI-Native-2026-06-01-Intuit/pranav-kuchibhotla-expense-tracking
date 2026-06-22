package com.uptimecrew.expense.outbox;

import java.time.Instant;
import java.util.List;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class OutboxPublisher {

    private static final Logger LOG = LoggerFactory.getLogger(OutboxPublisher.class);

    private final EventOutboxRepository repository;
    private final KafkaTemplate<String, String> kafkaTemplate;

    public OutboxPublisher(EventOutboxRepository repository,
                           KafkaTemplate<String, String> kafkaTemplate) {
        this.repository = repository;
        this.kafkaTemplate = kafkaTemplate;
    }

    @Scheduled(fixedDelay = 1000L)
    @Transactional
    public void publishPending() {
        List<EventOutboxEntity> batch =
                repository.findUnpublishedForUpdate(PageRequest.of(0, 50));
        for (EventOutboxEntity row : batch) {
            try {
                kafkaTemplate.send(row.getTopic(), row.getAggregateId(), row.getPayload())
                        .get(5, TimeUnit.SECONDS);
                row.markPublished(Instant.now());
                LOG.debug("published outbox row id={} topic={}", row.getId(), row.getTopic());
            } catch (Exception ex) {
                LOG.warn("failed to publish outbox row id={} topic={}: {}",
                        row.getId(), row.getTopic(), ex.getMessage());
            }
        }
    }
}
