package com.uptimecrew.expense.kafka;

import java.nio.charset.StandardCharsets;

import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.header.Header;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.support.ProducerListener;
import org.springframework.stereotype.Component;

@Component
public final class TraceparentLoggingProducerListener implements ProducerListener<Object, Object> {

    private static final Logger LOG = LoggerFactory.getLogger(TraceparentLoggingProducerListener.class);

    @Override
    public void onSuccess(ProducerRecord<Object, Object> record, RecordMetadata recordMetadata) {
        Header header = record.headers().lastHeader("traceparent");
        if (header != null && header.value() != null) {
            String value = new String(header.value(), StandardCharsets.UTF_8);
            LOG.info("outgoing traceparent={} topic={} key={}", value, record.topic(), record.key());
        } else {
            LOG.warn("outgoing kafka record has NO traceparent header topic={} key={}",
                    record.topic(), record.key());
        }
    }
}
