package com.uptimecrew.expense.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;

/**
 * Emits exactly one INFO log line per HTTP request after the response is written. Runs at the
 * lowest ordinary precedence so Spring MVC has already populated the best-matching pattern
 * attribute; we log that instead of the raw URI to keep cardinality bounded.
 *
 * <p>The OpenTelemetry Java agent's logback MDC instrumentation injects {@code trace_id} and
 * {@code span_id} into the SLF4J MDC for every log call made inside a server span, and
 * {@code logback-spring.xml} whitelists those keys in the LogstashEncoder. That means each of
 * these request-completion lines lands in Loki with the same {@code trace_id} that Tempo
 * recorded for the request — which is exactly what the Grafana Tempo → Logs pivot searches for.
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE - 10)
public class RequestCompletionLogFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestCompletionLogFilter.class);

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        long startNanos = System.nanoTime();
        try {
            chain.doFilter(request, response);
        } finally {
            long durationMs = (System.nanoTime() - startNanos) / 1_000_000L;
            String uriPattern = resolveUriPattern(request);
            log.info("http_request method={} uri={} status={} duration_ms={}",
                    request.getMethod(), uriPattern, response.getStatus(), durationMs);
        }
    }

    // Prefer the matched pattern (e.g., "/api/merchants/{id}") over the raw URI so
    // path variables don't blow up log cardinality. Falls back to the raw URI when
    // no handler matched (404s, static resources, actuator paths not routed via MVC).
    private String resolveUriPattern(HttpServletRequest request) {
        Object pattern = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
        if (pattern instanceof String s && !s.isBlank()) {
            return s;
        }
        return request.getRequestURI();
    }
}
