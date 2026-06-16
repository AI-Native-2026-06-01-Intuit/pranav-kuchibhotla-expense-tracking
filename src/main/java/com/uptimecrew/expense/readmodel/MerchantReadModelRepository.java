package com.uptimecrew.expense.readmodel;

import java.util.List;
import org.springframework.data.mongodb.repository.MongoRepository;

/** Spring Data MongoDB repository for the {@link MerchantReadModel} document. */
public interface MerchantReadModelRepository extends MongoRepository<MerchantReadModel, String> {

    List<MerchantReadModel> findByMccCode(String mccCode);
}
