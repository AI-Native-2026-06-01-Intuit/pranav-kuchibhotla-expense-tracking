package com.uptimecrew.expense.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    private static final String SECURITY_SCHEME_NAME = "bearer-jwt";

    @Bean
    public OpenAPI expenseOpenApi() {
        return new OpenAPI()
            .info(new Info()
                .title("Merchants API")
                .version("v1.0.0")
                .description("Merchants read and LLM-summary endpoints. "
                    + "Protected by Bearer JWT; callers require merchant read permissions "
                    + "(scope SCOPE_merchants.read and role MERCHANT_READER)."))
            .addSecurityItem(new SecurityRequirement().addList(SECURITY_SCHEME_NAME))
            .components(new Components()
                .addSecuritySchemes(SECURITY_SCHEME_NAME, new SecurityScheme()
                    .type(SecurityScheme.Type.HTTP)
                    .scheme("bearer")
                    .bearerFormat("JWT")));
    }
}
