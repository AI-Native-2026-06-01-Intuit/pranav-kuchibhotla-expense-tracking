package com.uptimecrew.expense.security;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.convert.converter.Converter;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity(prePostEnabled = true)
public class SecurityConfig {

    private final RateLimitFilter rateLimitFilter;

    public SecurityConfig(RateLimitFilter rateLimitFilter) {
        this.rateLimitFilter = rateLimitFilter;
    }

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        // CSRF disabled: this is a stateless Bearer-token (JWT) API with no browser session cookies,
        // so the cookie-based CSRF threat model does not apply. If cookie/session login is added
        // later (e.g. a browser-facing form login), CSRF protection MUST be re-enabled.
        http
            .csrf(csrf -> csrf.disable())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/actuator/health").permitAll()
                .requestMatchers("/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                .requestMatchers("/graphql", "/graphiql/**", "/graphql/schema").permitAll()
                .requestMatchers("/api/**").authenticated()
                .anyRequest().denyAll())
            .oauth2ResourceServer(oauth2 -> oauth2
                .jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthenticationConverter())))
            .addFilterAfter(rateLimitFilter, BearerTokenAuthenticationFilter.class);

        return http.build();
    }

    private Converter<Jwt, AbstractAuthenticationToken> jwtAuthenticationConverter() {
        JwtGrantedAuthoritiesConverter scopeConverter = new JwtGrantedAuthoritiesConverter();

        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(jwt -> {
            Collection<GrantedAuthority> authorities = new ArrayList<>(scopeConverter.convert(jwt));
            for (String role : extractRoles(jwt)) {
                authorities.add(new SimpleGrantedAuthority("ROLE_" + role));
            }
            return authorities;
        });
        return converter;
    }

    private static List<String> extractRoles(Jwt jwt) {
        Object claim = jwt.getClaim("roles");
        if (claim instanceof List<?> raw) {
            List<String> roles = new ArrayList<>(raw.size());
            for (Object element : raw) {
                if (element instanceof String s) {
                    roles.add(s);
                }
            }
            return roles;
        }
        return List.of();
    }
}
