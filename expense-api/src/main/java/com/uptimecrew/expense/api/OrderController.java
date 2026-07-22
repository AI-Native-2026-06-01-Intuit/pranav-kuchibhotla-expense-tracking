package com.uptimecrew.expense.api;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.uptimecrew.expense.service.SyntheticOrderService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.enums.ParameterIn;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;

/**
 * Synthetic orders + refunds REST controller.
 *
 * <p>Added for W7D4: the capstone repo does not ship a native orders
 * service, so this controller exposes just enough of an
 * order/idempotent-refund surface for the MCP {@code orders.get_order}
 * and {@code orders.create_refund} tools to route against real Spring
 * endpoints.
 */
@RestController
@RequestMapping("/api/v1/orders")
@Tag(name = "Orders", description = "Synthetic order read + idempotent refund write surface (W7D4)")
public class OrderController {

    private static final Logger LOG = LoggerFactory.getLogger(OrderController.class);

    private final SyntheticOrderService service;

    public OrderController(SyntheticOrderService service) {
        this.service = service;
    }

    @Operation(
        summary = "Get order by id",
        description = "Returns the synthetic order for the given id, scoped to the "
            + "tenant supplied via the X-Tenant-Id header. Requires a Bearer JWT "
            + "with scope orders.read and role ORDERS_READER.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Order found"),
        @ApiResponse(responseCode = "400", description = "Missing tenant header"),
        @ApiResponse(responseCode = "401", description = "Missing or invalid JWT"),
        @ApiResponse(responseCode = "403", description = "JWT lacks required scope/role"),
        @ApiResponse(responseCode = "404", description = "Order not found for tenant")
    })
    @GetMapping("/{orderId}")
    @PreAuthorize("hasAuthority('SCOPE_orders.read') and hasRole('ORDERS_READER')")
    public ResponseEntity<OrderView> getOrder(
            @PathVariable String orderId,
            @RequestHeader(value = "X-Tenant-Id", required = false) String tenantId,
            @AuthenticationPrincipal Jwt jwt) {
        LOG.info("GET /api/v1/orders/{} tenant={} subject={}", orderId, tenantId, jwt.getSubject());
        if (tenantId == null || tenantId.isBlank()) {
            return ResponseEntity.badRequest().build();
        }
        Optional<OrderView> result = service.getOrder(orderId, tenantId);
        return result.map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @Operation(
        summary = "Create an idempotent refund for an order",
        description = "Creates a refund and returns its refund_id. The composite key "
            + "(order_id, idempotency_key) is unique, so a repeat call with the same "
            + "UUID v4 returns the same refund_id and does not debit the ledger a second "
            + "time. Requires a Bearer JWT with scope orders.write and role ORDERS_WRITER.",
        parameters = @Parameter(name = "Idempotency-Key", in = ParameterIn.HEADER,
            required = true, description = "UUID v4 idempotency key; must equal the body key"))
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Refund returned (new or idempotent replay)"),
        @ApiResponse(responseCode = "400", description = "Missing/mismatched key, bad tenant, or malformed body"),
        @ApiResponse(responseCode = "401", description = "Missing or invalid JWT"),
        @ApiResponse(responseCode = "403", description = "JWT lacks required scope/role"),
        @ApiResponse(responseCode = "404", description = "Order not found for tenant")
    })
    @PostMapping("/{orderId}/refunds")
    @PreAuthorize("hasAuthority('SCOPE_orders.write') and hasRole('ORDERS_WRITER')")
    public ResponseEntity<?> createRefund(
            @PathVariable String orderId,
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKeyHeader,
            @RequestBody(required = false) CreateRefundRequest body,
            @AuthenticationPrincipal Jwt jwt) {
        LOG.info("POST /api/v1/orders/{}/refunds subject={}", orderId, jwt.getSubject());

        if (body == null || body.amount() == null || body.reason() == null
                || body.tenantId() == null || body.idempotencyKey() == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "missing_field"));
        }
        if (idempotencyKeyHeader == null || idempotencyKeyHeader.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "missing_idempotency_key_header"));
        }
        if (!idempotencyKeyHeader.equals(body.idempotencyKey())) {
            return ResponseEntity.badRequest().body(Map.of("error", "idempotency_key_mismatch"));
        }

        UUID parsedKey;
        try {
            parsedKey = UUID.fromString(idempotencyKeyHeader);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", "malformed_idempotency_key"));
        }
        // Rubric requires UUID v4 for refund writes.
        if (parsedKey.version() != 4) {
            return ResponseEntity.badRequest().body(Map.of("error", "idempotency_key_not_uuid_v4"));
        }
        if (body.amount().signum() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "amount_must_be_positive"));
        }

        try {
            RefundView refund = service.createRefund(
                    orderId,
                    body.tenantId(),
                    body.amount(),
                    body.reason(),
                    idempotencyKeyHeader);
            return ResponseEntity.ok(refund);
        } catch (SyntheticOrderService.OrderNotFoundException e) {
            return ResponseEntity.notFound().build();
        }
    }
}
