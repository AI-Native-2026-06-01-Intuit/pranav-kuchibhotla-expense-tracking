package com.uptimecrew.expense.graphql;

import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.BatchMapping;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.stereotype.Controller;

import com.uptimecrew.expense.llm.LlmSummaryService;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@Controller
public class MerchantGraphQlController {

    private static final Logger LOG = LoggerFactory.getLogger(MerchantGraphQlController.class);
    private static final int DEFAULT_LIMIT = 10;

    private final ExpenseClassificationService classificationService;
    private final LlmSummaryService llmSummaryService;

    public MerchantGraphQlController(ExpenseClassificationService classificationService,
                                     LlmSummaryService llmSummaryService) {
        this.classificationService = Objects.requireNonNull(classificationService,
                "classificationService must not be null");
        this.llmSummaryService = Objects.requireNonNull(llmSummaryService,
                "llmSummaryService must not be null");
    }

    @QueryMapping
    public MerchantReadModel merchant(@Argument String id) {
        LOG.info("graphql merchant query id={}", id);
        return classificationService.findById(id).orElse(null);
    }

    @QueryMapping
    public List<MerchantReadModel> latestMerchants(@Argument Integer limit) {
        int effective = limit == null ? DEFAULT_LIMIT : limit;
        LOG.info("graphql latestMerchants query limit={}", effective);
        return classificationService.findLatest(effective);
    }

    @MutationMapping
    public MerchantSummary summarizeMerchant(@Argument String id) {
        LOG.info("graphql summarizeMerchant mutation id={}", id);
        return llmSummaryService.summarize(id);
    }

    @BatchMapping(typeName = "Merchant", field = "lines")
    public Map<MerchantReadModel, List<LineItem>> lines(List<MerchantReadModel> parents) {
        LOG.info("graphql batch lines for {} merchant(s)", parents.size());
        return classificationService.loadLineItemsByParent(parents);
    }
}
