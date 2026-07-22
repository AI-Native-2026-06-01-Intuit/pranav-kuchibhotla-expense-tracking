package com.uptimecrew.expense.repository;

import com.uptimecrew.expense.entity.SyntheticRefund;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface SyntheticRefundRepository extends JpaRepository<SyntheticRefund, String> {

    Optional<SyntheticRefund> findByOrderIdAndIdempotencyKey(String orderId, String idempotencyKey);
}
