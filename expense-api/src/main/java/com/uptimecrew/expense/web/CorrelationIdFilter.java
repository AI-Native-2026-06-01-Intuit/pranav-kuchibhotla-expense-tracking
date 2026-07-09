package com.uptimecrew.expense.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Reads {@code x-correlation-id} from the incoming request (case-insensitive) and puts it into
 * SLF4J MDC under key {@code correlationId} for the duration of the request. If the header is
 * absent, generates a fresh UUID.
 *
 * <p>Registered with the highest ordinary precedence so it runs before Spring Security and any
 * business handlers, meaning every log line — including Spring Security 401s and actuator scrapes
 * — carries a correlation id. LogstashEncoder in logback-spring.xml is configured to include the
 * {@code correlationId} MDC key in the JSON output, so downstream (Loki, Tempo → logs pivot) can
 * search by it.
 *
 * <p>Response header is echoed back so callers can correlate their side of the trace.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class CorrelationIdFilter extends OncePerRequestFilter {

    static final String HEADER = "x-correlation-id";
    static final String MDC_KEY = "correlationId";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String supplied = request.getHeader(HEADER);
        String correlationId = (supplied != null && !supplied.isBlank())
                ? supplied
                : UUID.randomUUID().toString();
        MDC.put(MDC_KEY, correlationId);
        response.setHeader(HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            // Threads are pooled by Tomcat, so leaving MDC populated would leak the id into an
            // unrelated request handled on the same thread later.
            MDC.remove(MDC_KEY);
        }
    }
}
