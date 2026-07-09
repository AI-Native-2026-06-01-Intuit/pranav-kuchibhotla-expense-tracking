package com.uptimecrew.expense_tracking.lambda;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.amazonaws.services.lambda.runtime.Context;
import com.amazonaws.services.lambda.runtime.events.APIGatewayV2HTTPEvent;
import com.amazonaws.services.lambda.runtime.events.APIGatewayV2HTTPResponse;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.AttributeValue;
import software.amazon.awssdk.services.dynamodb.model.GetItemRequest;
import software.amazon.awssdk.services.dynamodb.model.GetItemResponse;

class MerchantLookupHandlerTest {

  private static Context stubContext(String requestId) {
    Context ctx = mock(Context.class);
    when(ctx.getAwsRequestId()).thenReturn(requestId);
    return ctx;
  }

  @Test
  void missingPathParamReturns400() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    MerchantLookupHandler handler = new MerchantLookupHandler(ddb, "merchants-test");

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of());

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-1"));

    assertThat(response.getStatusCode()).isEqualTo(400);
    assertThat(response.getHeaders())
        .containsEntry("Content-Type", "application/json")
        .containsEntry("x-correlation-id", "test-req-1");
    assertThat(response.getBody()).contains("merchantId");
    verifyNoInteractions(ddb);
  }

  @Test
  void blankMerchantIdReturns400() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    MerchantLookupHandler handler = new MerchantLookupHandler(ddb, "merchants-test");

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "   "));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-blank"));

    assertThat(response.getStatusCode()).isEqualTo(400);
    verifyNoInteractions(ddb);
  }

  @Test
  void callerSuppliedCorrelationIdIsEchoed() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    MerchantLookupHandler handler = new MerchantLookupHandler(ddb, "merchants-test");

    Map<String, String> headers = new LinkedHashMap<>();
    headers.put("X-Correlation-Id", "caller-corr-42");
    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setHeaders(headers);
    event.setPathParameters(Map.of());

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("aws-req-should-lose"));

    assertThat(response.getHeaders())
        .containsEntry("x-correlation-id", "caller-corr-42");
  }

  @Test
  void missingMerchantReturns404() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    when(ddb.getItem(any(GetItemRequest.class)))
        .thenReturn(GetItemResponse.builder().item(Map.of()).build());

    MerchantLookupHandler handler = new MerchantLookupHandler(ddb, "merchants-test");

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "mer_nope"));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-404"));

    assertThat(response.getStatusCode()).isEqualTo(404);
    assertThat(response.getHeaders())
        .containsEntry("x-correlation-id", "test-req-404")
        .containsEntry("Content-Type", "application/json");
    assertThat(response.getBody()).contains("mer_nope");
  }

  @Test
  void localFixtureReturns200ForKnownMerchantWithoutDynamoDb() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    MerchantLookupHandler handler =
        new MerchantLookupHandler(ddb, "merchants-test", () -> true);

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "mer_synth_001"));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-local-hit"));

    assertThat(response.getStatusCode()).isEqualTo(200);
    assertThat(response.getBody())
        .contains("mer_synth_001")
        .contains("Synthetic Coffee Co")
        .contains("25.00");
    assertThat(response.getHeaders())
        .containsEntry("x-correlation-id", "test-req-local-hit");
    verifyNoInteractions(ddb);
  }

  @Test
  void localFixtureReturns404ForUnknownMerchantWithoutDynamoDb() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    MerchantLookupHandler handler =
        new MerchantLookupHandler(ddb, "merchants-test", () -> true);

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "mer_nope"));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-local-miss"));

    assertThat(response.getStatusCode()).isEqualTo(404);
    verifyNoInteractions(ddb);
  }

  @Test
  void fixtureDisabledStillHitsDynamoDb() {
    DynamoDbClient ddb = mock(DynamoDbClient.class);
    Mockito.when(ddb.getItem(any(GetItemRequest.class)))
        .thenReturn(GetItemResponse.builder().item(Map.of()).build());
    MerchantLookupHandler handler =
        new MerchantLookupHandler(ddb, "merchants-test", () -> false);

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "mer_synth_001"));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-no-fixture"));

    // fixture is off, so this should have gone to (mocked) DDB and returned 404
    assertThat(response.getStatusCode()).isEqualTo(404);
  }

  @Test
  void merchantFoundReturns200Json() {
    Map<String, AttributeValue> item = new LinkedHashMap<>();
    item.put("id", AttributeValue.builder().s("mer_synth_001").build());
    item.put("name", AttributeValue.builder().s("Synthetic Coffee Co").build());
    item.put("category", AttributeValue.builder().s("Meals").build());
    item.put("defaultLimit", AttributeValue.builder().n("25.5").build());
    item.put("createdAt", AttributeValue.builder().s("2026-07-01T12:00:00Z").build());
    item.put("updatedAt", AttributeValue.builder().s("2026-07-02T12:00:00Z").build());

    DynamoDbClient ddb = mock(DynamoDbClient.class);
    when(ddb.getItem(any(GetItemRequest.class)))
        .thenReturn(GetItemResponse.builder().item(item).build());

    MerchantLookupHandler handler = new MerchantLookupHandler(ddb, "merchants-test");

    APIGatewayV2HTTPEvent event = new APIGatewayV2HTTPEvent();
    event.setPathParameters(Map.of("merchantId", "mer_synth_001"));

    APIGatewayV2HTTPResponse response =
        handler.handleRequest(event, stubContext("test-req-200"));

    assertThat(response.getStatusCode()).isEqualTo(200);
    assertThat(response.getBody())
        .contains("mer_synth_001")
        .contains("Synthetic Coffee Co")
        .contains("25.50");
  }
}
