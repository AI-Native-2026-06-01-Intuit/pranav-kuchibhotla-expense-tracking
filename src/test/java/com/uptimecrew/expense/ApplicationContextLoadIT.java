package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Collections;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import com.uptimecrew.expense.outbox.EventOutboxRepository;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.repository.MerchantRepository;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@SpringBootTest(properties = {
        "spring.autoconfigure.exclude="
                + "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.data.jpa.JpaRepositoriesAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.mongo.MongoAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.data.mongo.MongoDataAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.data.mongo.MongoRepositoriesAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration,"
                + "org.springframework.boot.autoconfigure.data.redis.RedisRepositoriesAutoConfiguration",
        "spring.cache.type=none",
        // No real broker in this smoke test; Kafka clients are lazy so this is
        // never dialed. The @MockitoBean KafkaTemplate overrides the autoconfig'd
        // producer bean used by OutboxPublisher.
        "spring.kafka.bootstrap-servers=PLAINTEXT://localhost:0",
        "spring.kafka.listener.auto-startup=false"
})
@ActiveProfiles("test")
class ApplicationContextLoadIT {

    @Autowired
    ExpenseClassificationService service;

    @MockitoBean
    MerchantRepository merchantRepository;

    @MockitoBean
    MerchantReadModelRepository merchantReadModelRepository;

    @MockitoBean
    StringRedisTemplate stringRedisTemplate;

    @MockitoBean
    EventOutboxRepository eventOutboxRepository;

    @MockitoBean
    KafkaTemplate<String, String> kafkaTemplate;

    @BeforeEach
    void stubEmptyOutbox() {
        // The scheduled OutboxPublisher fires every 1s; default Mockito returns
        // null for List, which would NPE the publisher's for-each loop.
        Mockito.when(eventOutboxRepository.findUnpublishedForUpdate(Mockito.any(Pageable.class)))
                .thenReturn(Collections.emptyList());
    }

    @Test
    void context_loads_and_service_bean_is_wired() {
        assertThat(service).isNotNull();
    }
}
