package com.uptimecrew.expense.security;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.Refill;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

// Rate limiter for the LLM summary endpoint(s).
// Uses an in-memory ConcurrentHashMap<String, Bucket> keyed by JWT subject.
// In-memory is acceptable for this assignment because we run a single app instance.
// In production this MUST be replaced with bucket4j-redis (already on the classpath
// from W3D1 Task 0) so the bucket state is shared across all app instances behind
// the load balancer — otherwise N replicas each grant the full limit and the
// effective per-subject quota becomes N × intended.
@Component
public class RateLimitFilter extends OncePerRequestFilter {

    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String uri = request.getRequestURI();
        if (!uri.startsWith("/api/") || !uri.endsWith("/summary")) {
            chain.doFilter(request, response);
            return;
        }

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (!(auth instanceof JwtAuthenticationToken jwtAuth)) {
            // Anonymous / non-JWT requests: don't enforce here — the security
            // filter chain is responsible for 401/403.
            chain.doFilter(request, response);
            return;
        }

        String subject = jwtAuth.getToken().getSubject();
        Bucket bucket = buckets.computeIfAbsent(subject, k -> newBucket());

        if (bucket.tryConsume(1)) {
            chain.doFilter(request, response);
            return;
        }

        response.setStatus(429);
        response.setHeader("Retry-After", "60");
        response.setContentType("application/json");
        response.getWriter().write("{\"error\":\"rate_limited\"}");
    }

    private static Bucket newBucket() {
        Bandwidth limit = Bandwidth.classic(10, Refill.intervally(10, Duration.ofMinutes(1)));
        return Bucket.builder().addLimit(limit).build();
    }
}
