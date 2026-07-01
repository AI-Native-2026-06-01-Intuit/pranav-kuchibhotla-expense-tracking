package com.uptimecrew.expense.mcp;

import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@Service
public class MerchantMcpServer {

    private static final Logger LOG = LoggerFactory.getLogger(MerchantMcpServer.class);

    private final ExpenseClassificationService service;

    public MerchantMcpServer(ExpenseClassificationService service) {
        this.service = service;
    }

    @Tool(description = "Look up a merchant by id and return its summary read model")
    public Optional<MerchantReadModel> lookupMerchant(
            @ToolParam(description = "The merchant id") String id) {
        LOG.info("MCP lookupMerchant id={}", id);
        return service.findById(id);
    }
}
