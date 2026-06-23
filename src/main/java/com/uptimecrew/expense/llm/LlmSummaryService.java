package com.uptimecrew.expense.llm;

import java.io.IOException;
import java.io.InputStream;
import java.util.Objects;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.beans.factory.annotation.Value;
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

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;

@Service
public class LlmSummaryService {

    private static final Logger LOG = LoggerFactory.getLogger(LlmSummaryService.class);
    private static final String SCHEMA_PATH = "schemas/MerchantSummary.schema.json";
    private static final String TRACER_NAME = "com.uptimecrew.expense.llm";

    private final ChatClient chatClient;
    private final MerchantReadModelRepository merchantReadModelRepository;
    private final ObjectMapper objectMapper;
    private final JsonSchema schema;
    private final Tracer tracer;
    private final String model;

    public LlmSummaryService(ChatClient.Builder chatClientBuilder,
                             MerchantReadModelRepository merchantReadModelRepository,
                             ObjectMapper objectMapper,
                             OpenTelemetry openTelemetry,
                             @Value("${spring.ai.anthropic.chat.options.model:claude-sonnet-4-5}")
                             String model) {
        this.chatClient = Objects.requireNonNull(chatClientBuilder, "chatClientBuilder").build();
        this.merchantReadModelRepository = Objects.requireNonNull(
                merchantReadModelRepository, "merchantReadModelRepository");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper");
        this.schema = loadSchema();
        this.tracer = Objects.requireNonNull(openTelemetry, "openTelemetry").getTracer(TRACER_NAME);
        this.model = Objects.requireNonNull(model, "model");
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

        Span span = tracer.spanBuilder("llm.summarize")
                .setSpanKind(SpanKind.CLIENT)
                .setAttribute("llm.model", model)
                .setAttribute("llm.input.aggregate_id", id)
                .startSpan();
        try (Scope scope = span.makeCurrent()) {
            ChatClient.CallResponseSpec spec = chatClient.prompt().user(prompt).call();
            MerchantSummary candidate = spec.entity(MerchantSummary.class);
            ChatResponse chatResponse = spec.chatResponse();

            span.setAttribute("llm.tokens.in", promptTokens(chatResponse));
            span.setAttribute("llm.tokens.out", completionTokens(chatResponse));

            validate(candidate);
            LOG.info("validated llm summary for merchant id={} mccCode={}",
                    id, candidate.mccCode());
            span.setStatus(StatusCode.OK);
            return candidate;
        } catch (RuntimeException ex) {
            span.recordException(ex);
            span.setStatus(StatusCode.ERROR, ex.getClass().getSimpleName());
            throw ex;
        } finally {
            span.end();
        }
    }

    void validate(MerchantSummary candidate) {
        JsonNode node = objectMapper.valueToTree(candidate);
        Set<ValidationMessage> errors = schema.validate(node);
        if (!errors.isEmpty()) {
            throw new IllegalStateException(
                    "MerchantSummary failed JSON Schema validation: " + errors);
        }
    }

    private static long promptTokens(ChatResponse response) {
        Usage usage = usageOf(response);
        if (usage == null || usage.getPromptTokens() == null) {
            return 0L;
        }
        return usage.getPromptTokens().longValue();
    }

    private static long completionTokens(ChatResponse response) {
        Usage usage = usageOf(response);
        if (usage == null || usage.getCompletionTokens() == null) {
            return 0L;
        }
        return usage.getCompletionTokens().longValue();
    }

    private static Usage usageOf(ChatResponse response) {
        if (response == null || response.getMetadata() == null) {
            return null;
        }
        return response.getMetadata().getUsage();
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
