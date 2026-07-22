package com.uptimecrew.expense.repository;

import com.uptimecrew.expense.entity.SyntheticOrder;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface SyntheticOrderRepository extends JpaRepository<SyntheticOrder, String> {

    Optional<SyntheticOrder> findByIdAndTenantId(String id, String tenantId);
}
