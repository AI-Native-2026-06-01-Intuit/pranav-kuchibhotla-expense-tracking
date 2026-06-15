package com.uptimecrew.expense.repository;

import com.uptimecrew.expense.entity.Rule;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

/**
 * Spring Data repository for the {@link Rule} entity.
 */
@Repository
public interface RuleRepository extends JpaRepository<Rule, String> {

    Optional<Rule> findByRuleName(String ruleName);

    List<Rule> findByActiveTrue();

    @Query("""
            SELECT r
            FROM Rule r
            WHERE r.active = true
              AND r.ruleType = :ruleType
            ORDER BY r.minimumAmount ASC
            """)
    List<Rule> findActiveByType(@Param("ruleType") String ruleType);
}
