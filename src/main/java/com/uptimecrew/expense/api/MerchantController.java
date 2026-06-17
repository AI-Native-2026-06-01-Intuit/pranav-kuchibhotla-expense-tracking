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
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;

@RestController
@RequestMapping("/api/v1/merchants")
@Tag(name = "Merchants", description = "Merchants read API and LLM-summary endpoint")
public class MerchantController {

    private static final Logger LOG = LoggerFactory.getLogger(MerchantController.class);

    private final ExpenseClassificationService service;

    public MerchantController(ExpenseClassificationService service) {
        this.service = service;
    }

    @Operation(
        summary = "Get merchant by id",
        description = "Returns the merchant read model for the given id. "
            + "Requires a Bearer JWT with scope merchants.read and role MERCHANT_READER.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Merchant found"),
        @ApiResponse(responseCode = "401", description = "Missing or invalid JWT"),
        @ApiResponse(responseCode = "403", description = "JWT lacks required scope/role"),
        @ApiResponse(responseCode = "404", description = "Merchant not found")
    })
    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('SCOPE_merchants.read') and hasRole('MERCHANT_READER')")
    public ResponseEntity<MerchantReadModel> getById(@PathVariable String id,
                                                     @AuthenticationPrincipal Jwt jwt) {
        LOG.info("GET /api/merchants/{} subject={}", id, jwt.getSubject());
        Optional<MerchantReadModel> result = service.findById(id);
        return result.map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @Operation(
        summary = "Get LLM summary for merchant",
        description = "Returns a short LLM-generated summary for the given merchant. "
            + "Rate-limited per caller; requires scope merchants.read and role MERCHANT_READER.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Summary returned"),
        @ApiResponse(responseCode = "401", description = "Missing or invalid JWT"),
        @ApiResponse(responseCode = "403", description = "JWT lacks required scope/role"),
        @ApiResponse(responseCode = "429", description = "Rate limit exceeded")
    })
    @GetMapping("/{id}/summary")
    @PreAuthorize("hasAuthority('SCOPE_merchants.read') and hasRole('MERCHANT_READER')")
    public Map<String, String> getSummary(@PathVariable String id,
                                          @AuthenticationPrincipal Jwt jwt) throws InterruptedException {
        LOG.info("GET /api/merchants/{}/summary subject={}", id, jwt.getSubject());
        Thread.sleep(100);
        return Map.of("summary", "Stub LLM summary for " + id);
    }
}
