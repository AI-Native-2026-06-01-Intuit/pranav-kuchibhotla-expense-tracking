package com.uptimecrew.expense.clients;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

@FeignClient(name = "identity", url = "${identity.base-url}")
public interface MerchantIdentityClient {

    @GetMapping("/identity/{userId}/profile")
    IdentityProfile getProfile(@PathVariable("userId") String userId);
}
