package com.microsoft.azure.spring.chatgpt.sample.cli;

import com.azure.ai.openai.OpenAIClientBuilder;
import com.azure.core.credential.AzureKeyCredential;
import com.azure.cosmos.CosmosClientBuilder;
import com.azure.cosmos.DirectConnectionConfig;
import com.azure.spring.data.cosmos.config.AbstractCosmosConfiguration;
import com.azure.spring.data.cosmos.repository.config.EnableCosmosRepositories;
import com.microsoft.azure.spring.chatgpt.sample.common.AzureOpenAIClient;
import com.microsoft.azure.spring.chatgpt.sample.common.DocumentIndexPlanner;
import com.microsoft.azure.spring.chatgpt.sample.common.vectorstore.CosmosDBVectorStore;
import com.microsoft.azure.spring.chatgpt.sample.common.vectorstore.CosmosEntityRepository;
import com.microsoft.azure.spring.chatgpt.sample.common.vectorstore.CosmosProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.io.IOException;

@Configuration
@EnableConfigurationProperties(CosmosProperties.class)
@EnableCosmosRepositories(basePackages = "com.microsoft.azure.spring.chatgpt.sample.common.vectorstore")
public class Config extends AbstractCosmosConfiguration {

    @Value("${AZURE_OPENAI_EMBEDDINGDEPLOYMENTID}")
    private String embeddingDeploymentId;

    @Value("${AZURE_OPENAI_CHATDEPLOYMENTID}")
    private String chatDeploymentId;

    @Value("${AZURE_OPENAI_ENDPOINT}")
    private String endpoint;

    @Value("${AZURE_OPENAI_APIKEY}")
    private String apiKey;

/*    @Value("${COSMOS_URI}")
    private String cosmosEndpoint;

    @Value("${COSMOS_KEY}")
    private String cosmosKey;*/


    @Autowired
    private CosmosProperties properties;

    @Autowired
    private CosmosEntityRepository cosmosEntityRepository;

    @Autowired
    private ApplicationContext applicationContext;

    //@Autowired
    //private CosmosTemplate cosmosTemplate;

    public Config() throws IOException {
    }

    @Override
    protected String getDatabaseName() {
        return properties.getDatabaseName();
    }

    @Bean
    public DocumentIndexPlanner planner(AzureOpenAIClient openAIClient, CosmosDBVectorStore vectorStore) {
        return new DocumentIndexPlanner(openAIClient, vectorStore);
    }

    @Bean
    public AzureOpenAIClient AzureOpenAIClient() {
        var innerClient = new OpenAIClientBuilder()
                .endpoint(endpoint)
                .credential(new AzureKeyCredential(apiKey))
                .buildClient();
        return new AzureOpenAIClient(innerClient, embeddingDeploymentId, null);
    }

    @Bean
    public CosmosClientBuilder cosmosClientBuilder() {
        DirectConnectionConfig directConnectionConfig = DirectConnectionConfig.getDefaultConfig();
        return new CosmosClientBuilder()
                .endpoint(properties.getUri())
                .key(properties.getKey())
                .directMode(directConnectionConfig);
    }

    @Bean
    public CosmosDBVectorStore vectorStore() {
        CosmosDBVectorStore store = new CosmosDBVectorStore(cosmosEntityRepository, properties.getContainerName(), properties.getDatabaseName(),applicationContext);
        return store;
    }
}
