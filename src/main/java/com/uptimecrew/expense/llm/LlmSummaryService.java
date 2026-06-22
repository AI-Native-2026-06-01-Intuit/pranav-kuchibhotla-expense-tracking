package com.uptimecrew.expense.llm;

import java.io.IOException;
import java.io.InputStream;
import java.util.Objects;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import com.uptimecrew.expense.graphql.MerchantSummary;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;

@Service
public class LlmSummaryService {

    private static final Logger LOG = LoggerFactory.getLogger(LlmSummaryService.class);
    private static final String SCHEMA_PATH = "schemas/MerchantSummary.schema.json";

    private final ChatClient chatClient;
    private final MerchantReadModelRepository merchantReadModelRepository;
    private final ObjectMapper objectMapper;
    private final JsonSchema schema;

    public LlmSummaryService(ChatClient.Builder chatClientBuilder,
                             MerchantReadModelRepository merchantReadModelRepository,
                             ObjectMapper objectMapper) {
        this.chatClient = Objects.requireNonNull(chatClientBuilder, "chatClientBuilder").build();
        this.merchantReadModelRepository = Objects.requireNonNull(
                merchantReadModelRepository, "merchantReadModelRepository");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper");
        this.schema = loadSchema();
    }

    public MerchantSummary summarize(String id) {
        Objects.requireNonNull(id, "id");
        MerchantReadModel merchant = merchantReadModelRepository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("merchant not found: " + id));

        String prompt = """
                Summarize the merchant below as JSON only, with no commentary,
                matching exactly these fields:
                  mccCode (string)
                  totalSpend (number)
                  transactionCount (integer, >= 0)
                  primaryCategory (string)

                Merchant:
                  id: %s
                  displayName: %s
                  mccCode: %s
                  merchantKind: %s
                  transactionCount: %d
                """.formatted(
                        merchant.getId(),
                        merchant.getDisplayName(),
                        merchant.getMccCode(),
                        merchant.getMerchantKind(),
                        merchant.getTransactions().size());

        MerchantSummary candidate = chatClient.prompt()
                .user(prompt)
                .call()
                .entity(MerchantSummary.class);

        validate(candidate);
        LOG.info("validated llm summary for merchant id={} mccCode={}",
                id, candidate.mccCode());
        return candidate;
    }

    void validate(MerchantSummary candidate) {
        JsonNode node = objectMapper.valueToTree(candidate);
        Set<ValidationMessage> errors = schema.validate(node);
        if (!errors.isEmpty()) {
            throw new IllegalStateException(
                    "MerchantSummary failed JSON Schema validation: " + errors);
        }
    }

    private static JsonSchema loadSchema() {
        ClassPathResource resource = new ClassPathResource(SCHEMA_PATH);
        try (InputStream in = resource.getInputStream()) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in);
        } catch (IOException ex) {
            throw new IllegalStateException(
                    "failed to load JSON schema " + SCHEMA_PATH, ex);
        }
    }
}
