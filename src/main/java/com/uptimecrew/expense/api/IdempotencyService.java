package com.uptimecrew.expense.api;

import java.time.Duration;
import java.util.Map;
import java.util.function.Supplier;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class IdempotencyService {

    private static final Logger LOG = LoggerFactory.getLogger(IdempotencyService.class);
    private static final String SENTINEL = "__in_flight__";
    private static final Duration TTL = Duration.ofHours(24);

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;

    public IdempotencyService(StringRedisTemplate redis, ObjectMapper mapper) {
        this.redis = redis;
        this.mapper = mapper;
    }

    public <T> ResponseEntity<T> handle(String key, String namespace, Supplier<ResponseEntity<T>> doWork) {
        String redisKey = "idem:" + namespace + ":" + key;

        String existing = redis.opsForValue().get(redisKey);
        if (existing != null) {
            if (SENTINEL.equals(existing)) {
                return ResponseEntity.status(409).build();
            }
            try {
                Map<String, Object> body = mapper.readValue(existing, Map.class);
                @SuppressWarnings("unchecked")
                T cached = (T) body;
                return ResponseEntity.ok(cached);
            } catch (JsonProcessingException e) {
                LOG.warn("Idempotency cache unreadable for key={}, recomputing", redisKey, e);
            }
        }

        Boolean acquired = redis.opsForValue().setIfAbsent(redisKey, SENTINEL, TTL);
        if (acquired == null || !acquired) {
            return ResponseEntity.status(409).build();
        }

        ResponseEntity<T> result = doWork.get();

        try {
            String json = mapper.writeValueAsString(result.getBody());
            redis.opsForValue().set(redisKey, json, TTL);
        } catch (JsonProcessingException e) {
            LOG.warn("Failed to cache idempotent response for key={}, clearing sentinel", redisKey, e);
            redis.delete(redisKey);
        }

        return result;
    }
}
