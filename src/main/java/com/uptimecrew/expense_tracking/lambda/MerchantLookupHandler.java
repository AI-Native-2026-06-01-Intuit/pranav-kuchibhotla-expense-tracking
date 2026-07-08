package com.uptimecrew.expense_tracking.lambda;

import com.amazonaws.services.lambda.runtime.Context;
import com.amazonaws.services.lambda.runtime.RequestHandler;
import com.amazonaws.services.lambda.runtime.events.APIGatewayV2HTTPEvent;
import com.amazonaws.services.lambda.runtime.events.APIGatewayV2HTTPResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import software.amazon.awssdk.core.client.config.ClientOverrideConfiguration;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.AttributeValue;
import software.amazon.awssdk.services.dynamodb.model.GetItemRequest;
import software.amazon.awssdk.services.dynamodb.model.GetItemResponse;

public final class MerchantLookupHandler
    implements RequestHandler<APIGatewayV2HTTPEvent, APIGatewayV2HTTPResponse> {

  private static final Logger LOG = LoggerFactory.getLogger(MerchantLookupHandler.class);
  private static final ObjectMapper JSON =
      new ObjectMapper()
          .registerModule(new JavaTimeModule())
          .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
  private static final String TABLE = System.getenv("MERCHANTS_TABLE");
  private static final String NAMESPACE = "ExpenseDev";
  private static final String CORRELATION_HEADER = "x-correlation-id";
  private static final DynamoDbClient DDB = buildClient();

  private final DynamoDbClient dynamoDb;
  private final String tableName;
  private final BooleanSupplier localFixtureEnabled;

  public MerchantLookupHandler() {
    this(DDB, TABLE, MerchantLookupHandler::isLocalFixtureEnabledFromEnv);
  }

  MerchantLookupHandler(DynamoDbClient dynamoDb, String tableName) {
    this(dynamoDb, tableName, () -> false);
  }

  MerchantLookupHandler(
      DynamoDbClient dynamoDb, String tableName, BooleanSupplier localFixtureEnabled) {
    this.dynamoDb = dynamoDb;
    this.tableName = tableName;
    this.localFixtureEnabled = localFixtureEnabled;
  }

  // Local-only escape hatch for `sam local invoke` and unit smoke checks. SAM sets
  // AWS_SAM_LOCAL=true when running the Lambda in Docker; real AWS never sets it,
  // so this branch cannot be reached in production. LOCAL_MERCHANT_FIXTURE_ENABLED
  // is an explicit opt-in used by tests and can be set from an event overrides file
  // without touching template.yaml. This exists because SAM local does not provision
  // DynamoDB — without a fixture the handler cannot exercise the 200 contract path.
  private static boolean isLocalFixtureEnabledFromEnv() {
    return "true".equalsIgnoreCase(System.getenv("AWS_SAM_LOCAL"))
        || "true".equalsIgnoreCase(System.getenv("LOCAL_MERCHANT_FIXTURE_ENABLED"));
  }

  private static DynamoDbClient buildClient() {
    String region = System.getenv("AWS_REGION");
    if (region == null || region.isBlank()) {
      region = "us-east-1";
    }
    return DynamoDbClient.builder()
        .region(Region.of(region))
        .httpClient(UrlConnectionHttpClient.builder().build())
        .overrideConfiguration(ClientOverrideConfiguration.builder().build())
        .build();
  }

  @Override
  public APIGatewayV2HTTPResponse handleRequest(APIGatewayV2HTTPEvent event, Context context) {
    String correlationId = resolveCorrelationId(event, context);
    String merchantId = extractMerchantId(event);

    if (merchantId == null || merchantId.isBlank()) {
      LOG.info("bad_request correlationId={} reason=missing_merchantId", correlationId);
      emitMetric("MerchantLookupBadRequest", correlationId);
      return respond(
          400,
          correlationId,
          Map.of("error", "merchantId path parameter is required"));
    }

    if (localFixtureEnabled.getAsBoolean()) {
      return handleLocalFixture(merchantId, correlationId);
    }

    if (tableName == null || tableName.isBlank()) {
      LOG.error("config_error correlationId={} reason=MERCHANTS_TABLE_not_set", correlationId);
      emitMetric("MerchantLookupBadRequest", correlationId);
      return respond(
          500,
          correlationId,
          Map.of("error", "server misconfigured: MERCHANTS_TABLE not set"));
    }

    try {
      GetItemResponse res =
          dynamoDb.getItem(
              GetItemRequest.builder()
                  .tableName(tableName)
                  .key(Map.of("id", AttributeValue.builder().s(merchantId).build()))
                  .consistentRead(false)
                  .build());

      if (!res.hasItem() || res.item().isEmpty()) {
        LOG.info("merchant_not_found correlationId={} merchantId={}", correlationId, merchantId);
        emitMetric("MerchantNotFound", correlationId);
        return respond(
            404,
            correlationId,
            Map.of("error", "merchant not found", "merchantId", merchantId));
      }

      MerchantRecord record = MerchantRecord.fromItem(res.item());
      LOG.info(
          "merchant_lookup_ok correlationId={} merchantId={}", correlationId, record.id());
      emitMetric("MerchantLookupSuccess", correlationId);
      return respond(200, correlationId, record);
    } catch (RuntimeException ex) {
      LOG.error(
          "merchant_lookup_error correlationId={} merchantId={} err={}",
          correlationId,
          merchantId,
          ex.toString());
      return respond(500, correlationId, Map.of("error", "internal error"));
    }
  }

  // Local-only fixture. Only reachable when AWS_SAM_LOCAL=true (SAM local invoke)
  // or LOCAL_MERCHANT_FIXTURE_ENABLED=true. Production Lambda never runs this.
  private APIGatewayV2HTTPResponse handleLocalFixture(String merchantId, String correlationId) {
    if ("mer_synth_001".equals(merchantId)) {
      MerchantRecord record =
          new MerchantRecord(
              "mer_synth_001",
              "Synthetic Coffee Co",
              "Meals",
              new BigDecimal("25.00"),
              Instant.parse("2026-07-01T12:00:00Z"),
              Instant.parse("2026-07-01T12:00:00Z"));
      LOG.info(
          "merchant_lookup_ok_local_fixture correlationId={} merchantId={}",
          correlationId,
          merchantId);
      emitMetric("MerchantLookupSuccess", correlationId);
      return respond(200, correlationId, record);
    }
    LOG.info(
        "merchant_not_found_local_fixture correlationId={} merchantId={}",
        correlationId,
        merchantId);
    emitMetric("MerchantNotFound", correlationId);
    return respond(
        404, correlationId, Map.of("error", "merchant not found", "merchantId", merchantId));
  }

  private static String extractMerchantId(APIGatewayV2HTTPEvent event) {
    if (event == null || event.getPathParameters() == null) {
      return null;
    }
    return event.getPathParameters().get("merchantId");
  }

  private static String resolveCorrelationId(APIGatewayV2HTTPEvent event, Context context) {
    if (event != null && event.getHeaders() != null) {
      for (Map.Entry<String, String> e : event.getHeaders().entrySet()) {
        if (CORRELATION_HEADER.equalsIgnoreCase(e.getKey())
            && e.getValue() != null
            && !e.getValue().isBlank()) {
          return e.getValue();
        }
      }
    }
    if (context != null && context.getAwsRequestId() != null) {
      return context.getAwsRequestId();
    }
    return UUID.randomUUID().toString();
  }

  private static APIGatewayV2HTTPResponse respond(int status, String correlationId, Object body) {
    String jsonBody;
    try {
      jsonBody = JSON.writeValueAsString(body);
    } catch (Exception ex) {
      jsonBody = "{\"error\":\"failed to serialize response\"}";
    }
    Map<String, String> headers = new LinkedHashMap<>();
    headers.put("Content-Type", "application/json");
    headers.put(CORRELATION_HEADER, correlationId);
    APIGatewayV2HTTPResponse response = new APIGatewayV2HTTPResponse();
    response.setStatusCode(status);
    response.setHeaders(headers);
    response.setBody(jsonBody);
    response.setIsBase64Encoded(false);
    return response;
  }

  private static void emitMetric(String metricName, String correlationId) {
    Map<String, Object> emf = new LinkedHashMap<>();
    Map<String, Object> aws = new LinkedHashMap<>();
    aws.put("Timestamp", System.currentTimeMillis());
    aws.put(
        "CloudWatchMetrics",
        java.util.List.of(
            Map.of(
                "Namespace", NAMESPACE,
                "Dimensions", java.util.List.of(java.util.List.of("service")),
                "Metrics",
                    java.util.List.of(Map.of("Name", metricName, "Unit", "Count")))));
    emf.put("_aws", aws);
    emf.put("service", "expense-merchant-lookup");
    emf.put("correlationId", correlationId);
    emf.put(metricName, 1);
    try {
      System.out.println(JSON.writeValueAsString(emf));
    } catch (Exception ex) {
      LOG.warn("emf_serialization_failed correlationId={} err={}", correlationId, ex.toString());
    }
  }

  public record MerchantRecord(
      String id,
      String name,
      String category,
      BigDecimal defaultLimit,
      Instant createdAt,
      Instant updatedAt) {

    public MerchantRecord {
      if (defaultLimit != null) {
        defaultLimit = defaultLimit.setScale(2, RoundingMode.HALF_UP);
      }
    }

    static MerchantRecord fromItem(Map<String, AttributeValue> item) {
      String id = stringOf(item, "id");
      String name = stringOf(item, "name");
      String category = stringOf(item, "category");
      BigDecimal defaultLimit = null;
      AttributeValue limit = item.get("defaultLimit");
      if (limit != null && limit.n() != null) {
        defaultLimit = new BigDecimal(limit.n()).setScale(2, RoundingMode.HALF_UP);
      }
      Instant createdAt = instantOf(item, "createdAt");
      Instant updatedAt = instantOf(item, "updatedAt");
      return new MerchantRecord(id, name, category, defaultLimit, createdAt, updatedAt);
    }

    private static String stringOf(Map<String, AttributeValue> item, String key) {
      AttributeValue v = item.get(key);
      return v == null ? null : v.s();
    }

    private static Instant instantOf(Map<String, AttributeValue> item, String key) {
      AttributeValue v = item.get(key);
      if (v == null || v.s() == null || v.s().isBlank()) {
        return null;
      }
      try {
        return Instant.parse(v.s());
      } catch (RuntimeException ex) {
        return null;
      }
    }
  }
}
