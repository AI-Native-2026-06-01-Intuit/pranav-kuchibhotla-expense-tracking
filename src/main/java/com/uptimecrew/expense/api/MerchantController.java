package com.uptimecrew.expense.api;

import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@RestController
@RequestMapping("/api/merchants")
public class MerchantController {

    private static final Logger LOG = LoggerFactory.getLogger(MerchantController.class);

    private final ExpenseClassificationService service;

    public MerchantController(ExpenseClassificationService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('SCOPE_merchants.read') and hasRole('MERCHANT_READER')")
    public ResponseEntity<MerchantReadModel> getById(@PathVariable String id,
                                                     @AuthenticationPrincipal Jwt jwt) {
        LOG.info("GET /api/merchants/{} subject={}", id, jwt.getSubject());
        Optional<MerchantReadModel> result = service.findById(id);
        return result.map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}/summary")
    @PreAuthorize("hasAuthority('SCOPE_merchants.read') and hasRole('MERCHANT_READER')")
    public Map<String, String> getSummary(@PathVariable String id,
                                          @AuthenticationPrincipal Jwt jwt) throws InterruptedException {
        LOG.info("GET /api/merchants/{}/summary subject={}", id, jwt.getSubject());
        Thread.sleep(100);
        return Map.of("summary", "Stub LLM summary for " + id);
    }
}
