package com.uptimecrew.expense.consumer;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;

@Component
public class MerchantClassifiedListener {

    private static final Logger LOG = LoggerFactory.getLogger(MerchantClassifiedListener.class);

    private final MerchantReadModelRepository readModelRepository;
    private final ObjectMapper objectMapper;

    public MerchantClassifiedListener(MerchantReadModelRepository readModelRepository,
                                      ObjectMapper objectMapper) {
        this.readModelRepository = readModelRepository;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(
            topics = "merchants.events",
            groupId = "expense-read-model-builder",
            containerFactory = "kafkaListenerContainerFactory")
    public void onEvent(String payload) throws Exception {
        MerchantClassifiedEvent event =
                objectMapper.readValue(payload, MerchantClassifiedEvent.class);
        MerchantReadModel document = readModelRepository.findById(event.aggregateId())
                .orElseGet(() -> new MerchantReadModel(event.aggregateId()));
        document.applyEvent(event);
        readModelRepository.save(document);
        LOG.info("consumed merchant event aggregateId={}", event.aggregateId());
    }
}
