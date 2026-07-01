package com.uptimecrew.expense.clients;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;

// The @CircuitBreaker annotation lives on this Spring-managed service wrapper,
// not on the MerchantIdentityClient Feign interface. Resilience4j's AOP advice
// is applied by Spring to beans whose proxy goes through Spring's bean
// post-processors; Feign clients are built by spring-cloud-openfeign and the
// circuit breaker advice does not reliably intercept their proxy methods.
// Wrapping the Feign call in a service method gives a single, well-defined
// boundary for the breaker and the fallback.
@Service
public class IdentityService {

    private static final Logger LOG = LoggerFactory.getLogger(IdentityService.class);

    private final MerchantIdentityClient client;

    public IdentityService(MerchantIdentityClient client) {
        this.client = client;
    }

    @CircuitBreaker(name = "identity", fallbackMethod = "fallbackProfile")
    public IdentityProfile getProfile(String userId) {
        return client.getProfile(userId);
    }

    private IdentityProfile fallbackProfile(String userId, Throwable t) {
        LOG.warn("Identity profile lookup failed for userId={}, returning fallback", userId, t);
        return new IdentityProfile(userId, "", "unknown");
    }
}
