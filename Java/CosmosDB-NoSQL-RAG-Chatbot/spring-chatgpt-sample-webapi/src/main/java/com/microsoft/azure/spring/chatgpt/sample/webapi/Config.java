package com.microsoft.azure.spring.chatgpt.sample.webapi;

import com.azure.ai.openai.OpenAIClientBuilder;
import com.azure.core.credential.AzureKeyCredential;
import com.azure.cosmos.CosmosClientBuilder;
import com.azure.cosmos.DirectConnectionConfig;
import com.azure.spring.data.cosmos.config.AbstractCosmosConfiguration;
import com.azure.spring.data.cosmos.config.CosmosConfig;
import com.azure.spring.data.cosmos.core.CosmosTemplate;
import com.azure.spring.data.cosmos.repository.config.EnableCosmosRepositories;
import com.microsoft.azure.spring.chatgpt.sample.common.AzureOpenAIClient;
import com.microsoft.azure.spring.chatgpt.sample.common.ChatPlanner;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosDBVectorStore;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosEntity;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosEntityRepository;
import com.microsoft.azure.spring.chatgpt.sample.common.store.VectorStore;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.io.IOException;
import java.util.logging.Logger;


@Configuration
@EnableConfigurationProperties(CosmosProperties.class)
@EnableCosmosRepositories(basePackages = "com.microsoft.azure.spring.chatgpt.sample.common.store")
public class Config extends AbstractCosmosConfiguration {

    @Autowired
    private CosmosProperties properties;
    @Autowired
    private CosmosEntityRepository cosmosEntityRepository;

    @Autowired
    private ApplicationContext applicationContext;

    @Autowired
    private CosmosTemplate cosmosTemplate;

    @Value("${AZURE_OPENAI_EMBEDDINGDEPLOYMENTID}")
    private String embeddingDeploymentId;

    @Value("${AZURE_OPENAI_CHATDEPLOYMENTID}")
    private String chatDeploymentId;

    @Value("${AZURE_OPENAI_ENDPOINT}")
    private String endpoint;

    @Value("${AZURE_OPENAI_APIKEY}")
    private String apiKey;

    @Value("${vector-store.file}")
    private String vectorJsonFile;

    private Logger log = Logger.getLogger(Config.class.getName());

    public Config() throws IOException {
    }

    @Override
    protected String getDatabaseName() {
        return properties.getDatabaseName();
    }

    @Bean
    public ChatPlanner planner(AzureOpenAIClient openAIClient, VectorStore vectorStore) {
        return new ChatPlanner(openAIClient, vectorStore);
    }

    @Bean
    public AzureOpenAIClient AzureOpenAIClient() {
        var innerClient = new OpenAIClientBuilder()
            .endpoint(endpoint)
            .credential(new AzureKeyCredential(apiKey))
            .buildClient();
        return new AzureOpenAIClient(innerClient, embeddingDeploymentId, chatDeploymentId);
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
    public CosmosConfig cosmosConfig() {
        return CosmosConfig.builder()
                .enableQueryMetrics(properties.isQueryMetricsEnabled())
                .build();
    }

    @Bean
    public VectorStore vectorStore() throws IOException {
        CosmosDBVectorStore store = new CosmosDBVectorStore(cosmosEntityRepository, properties.getContainerName(), properties.getDatabaseName(),applicationContext);
        String currentPath = new java.io.File(".").getCanonicalPath();;
        String path = currentPath+vectorJsonFile.replace(  "\\", "//");
        try{
            Iterable<CosmosEntity> FirstDocFound = cosmosEntityRepository.findRecord("a598dfb0-c58e-457e-977f-70f2786b5940").stream().toList();
            long FirstDocFoundSize = FirstDocFound.spliterator().getExactSizeIfKnown();
            //if the query succeeds, then we have data in the database loaded from elsewhere, so we don't need to load from file
            if (FirstDocFoundSize != 0) {
                store.loadFromJsonFile(path);
            }
        }
        catch (Exception e){
            log.warning("checked for existing data failed, so loading from file....");
            store.loadFromJsonFile(path);
            log.info("loaded from file!");
        }
        return store;
    }
}
