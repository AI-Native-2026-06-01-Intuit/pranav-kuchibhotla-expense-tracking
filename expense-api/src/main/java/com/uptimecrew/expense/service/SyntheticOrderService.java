package com.uptimecrew.expense.service;

import com.uptimecrew.expense.api.OrderView;
import com.uptimecrew.expense.api.RefundView;
import com.uptimecrew.expense.entity.SyntheticOrder;
import com.uptimecrew.expense.entity.SyntheticRefund;
import com.uptimecrew.expense.repository.SyntheticOrderRepository;
import com.uptimecrew.expense.repository.SyntheticRefundRepository;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Domain service for the synthetic W7D4 orders + refunds surface.
 *
 * <p>Idempotent refund contract: the composite unique key
 * {@code (order_id, idempotency_key)} means a repeat call with the same
 * UUID returns the previously-persisted refund_id without a second
 * ledger debit.
 */
@Service
public class SyntheticOrderService {

    private final SyntheticOrderRepository orders;
    private final SyntheticRefundRepository refunds;

    public SyntheticOrderService(SyntheticOrderRepository orders,
                                 SyntheticRefundRepository refunds) {
        this.orders = orders;
        this.refunds = refunds;
    }

    @Transactional(readOnly = true)
    public Optional<OrderView> getOrder(String orderId, String tenantId) {
        return orders.findByIdAndTenantId(orderId, tenantId).map(this::toView);
    }

    @Transactional
    public RefundView createRefund(String orderId,
                                   String tenantId,
                                   BigDecimal amount,
                                   String reason,
                                   String idempotencyKey) {
        Optional<SyntheticRefund> existing =
                refunds.findByOrderIdAndIdempotencyKey(orderId, idempotencyKey);
        if (existing.isPresent()) {
            return toView(existing.get());
        }

        SyntheticOrder order = orders.findByIdAndTenantId(orderId, tenantId)
                .orElseThrow(() -> new OrderNotFoundException(orderId, tenantId));

        BigDecimal scaled = amount.setScale(2, RoundingMode.HALF_UP);
        SyntheticRefund refund = new SyntheticRefund(
                "ref-" + UUID.randomUUID(),
                order.getId(),
                order.getTenantId(),
                scaled,
                reason,
                "SETTLED",
                idempotencyKey);
        SyntheticRefund saved = refunds.save(refund);
        return toView(saved);
    }

    private OrderView toView(SyntheticOrder o) {
        return new OrderView(
                o.getId(),
                o.getTenantId(),
                o.getTotalAmount(),
                o.getStatus(),
                o.getCreatedAt());
    }

    private RefundView toView(SyntheticRefund r) {
        return new RefundView(
                r.getId(),
                r.getOrderId(),
                r.getAmount(),
                r.getReason(),
                r.getStatus());
    }

    public static final class OrderNotFoundException extends RuntimeException {
        public OrderNotFoundException(String orderId, String tenantId) {
            super("order not found: " + orderId + " for tenant " + tenantId);
        }
    }
}
