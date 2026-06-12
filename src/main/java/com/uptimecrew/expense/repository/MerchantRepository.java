package com.uptimecrew.expense.repository;

import com.uptimecrew.expense.entity.Merchant;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * Spring Data repository for the {@link Merchant} entity.
 */
@Repository
public interface MerchantRepository extends JpaRepository<Merchant, String> {

    Optional<Merchant> findByNormalizedName(String normalizedName);

    @Query("""
            SELECT m
            FROM Merchant m
            WHERE SIZE(m.transactions) >= :minimumTransactions
            ORDER BY m.displayName
            """)
    List<Merchant> findWithAtLeastTransactions(@Param("minimumTransactions") int minimumTransactions);
}
