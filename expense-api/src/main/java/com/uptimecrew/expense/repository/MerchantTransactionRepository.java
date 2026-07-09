package com.uptimecrew.expense.repository;

import com.uptimecrew.expense.entity.MerchantTransaction;
import java.time.Instant;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * Spring Data repository for the {@link MerchantTransaction} entity.
 */
@Repository
public interface MerchantTransactionRepository extends JpaRepository<MerchantTransaction, String> {

    List<MerchantTransaction> findByTransactionKind(String transactionKind);

    @Query("""
            SELECT t
            FROM MerchantTransaction t
            WHERE t.merchant.id = :merchantId
              AND t.occurredAt >= :since
            ORDER BY t.occurredAt DESC
            """)
    List<MerchantTransaction> findForMerchantSince(@Param("merchantId") String merchantId,
                                                   @Param("since") Instant since);
}
