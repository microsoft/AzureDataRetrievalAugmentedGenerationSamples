package com.microsoft.azure.spring.chatgpt.sample.common.store;

import com.azure.cosmos.CosmosAsyncClient;
import com.azure.cosmos.CosmosAsyncDatabase;
import com.azure.cosmos.implementation.guava25.collect.ImmutableList;
import com.azure.cosmos.models.CosmosContainerProperties;
import com.azure.cosmos.models.CosmosContainerResponse;
import com.azure.cosmos.models.CosmosVectorDataType;
import com.azure.cosmos.models.CosmosVectorDistanceFunction;
import com.azure.cosmos.models.CosmosVectorEmbedding;
import com.azure.cosmos.models.CosmosVectorEmbeddingPolicy;
import com.azure.cosmos.models.CosmosVectorIndexSpec;
import com.azure.cosmos.models.CosmosVectorIndexType;
import com.azure.cosmos.models.ExcludedPath;
import com.azure.cosmos.models.IncludedPath;
import com.azure.cosmos.models.IndexingMode;
import com.azure.cosmos.models.IndexingPolicy;
import com.azure.cosmos.models.ThroughputProperties;
import com.azure.spring.data.cosmos.repository.config.EnableCosmosRepositories;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.stereotype.Component;
import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Logger;
import java.util.stream.Collectors;

@Component
@EnableCosmosRepositories (basePackages = "com.microsoft.azure.spring.chatgpt.sample.common.vectorstore")
public class CosmosDBVectorStore implements VectorStore {

    private final VectorStoreData data;

    @Autowired
    private CosmosEntityRepository cosmosEntityRepository;

    private String containerName;

    private String databaseName;

    private ApplicationContext applicationContext;

    private Logger log = Logger.getLogger(CosmosDBVectorStore.class.getName());

    public CosmosAsyncClient client;

    public CosmosDBVectorStore(CosmosEntityRepository cosmosEntityRepository, String containerName, String databaseName, ApplicationContext applicationContext) {
        this.cosmosEntityRepository = cosmosEntityRepository;
        this.applicationContext = applicationContext;
        client = applicationContext.getBean(CosmosAsyncClient.class);
        this.containerName = containerName;
        this.databaseName = databaseName;
        this.data = new VectorStoreData();
    }

    @Override
    public void saveDocument(String key, CosmosEntity doc) {
        cosmosEntityRepository.save(doc);
    }

    @Override
    public CosmosEntity getDocument(String key) {
        var doc = cosmosEntityRepository.findById(key).get();
        return doc;
    }

    @Override
    public void removeDocument(String key) {
        cosmosEntityRepository.deleteById(key);
    }

    @Override
    public List<CosmosEntity> searchTopKNearest(List<Double> embedding, int k) {
        return searchTopKNearest(embedding, k, 0);
    }

    @Override
    public List<CosmosEntity> searchTopKNearest(List<Double> embedding, int k, double cutOff) {
        Object embeddingParam = embedding.stream().map(aDouble -> (Float) (float) aDouble.doubleValue()).collect(Collectors.toList()).toArray();
        ArrayList<CosmosEntity> results = cosmosEntityRepository.vectorSearch(embeddingParam);
        return results;
    }

    public void createVectorIndex(int numLists, int dimensions, String similarity) {

        CosmosContainerProperties collectionDefinition = new CosmosContainerProperties(containerName, "/id");

        //set vector embedding policy
        CosmosVectorEmbeddingPolicy cosmosVectorEmbeddingPolicy = new CosmosVectorEmbeddingPolicy();
        CosmosVectorEmbedding embedding = new CosmosVectorEmbedding();
        embedding.setPath("/embedding");
        embedding.setDataType(CosmosVectorDataType.FLOAT32);
        embedding.setDimensions(1536L);
        embedding.setDistanceFunction(CosmosVectorDistanceFunction.COSINE);
        cosmosVectorEmbeddingPolicy.setCosmosVectorEmbeddings(Arrays.asList(embedding));
        collectionDefinition.setVectorEmbeddingPolicy(cosmosVectorEmbeddingPolicy);

        //set vector indexing policy
        IndexingPolicy indexingPolicy = new IndexingPolicy();
        indexingPolicy.setIndexingMode(IndexingMode.CONSISTENT);
        ExcludedPath excludedPath = new ExcludedPath("/*");
        indexingPolicy.setExcludedPaths(Collections.singletonList(excludedPath));
        IncludedPath includedPath1 = new IncludedPath("/hash/?");
        IncludedPath includedPath2 = new IncludedPath("/text/?");
        indexingPolicy.setIncludedPaths(ImmutableList.of(includedPath1, includedPath2));
        CosmosVectorIndexSpec cosmosVectorIndexSpec = new CosmosVectorIndexSpec();
        cosmosVectorIndexSpec.setPath("/embedding");
        cosmosVectorIndexSpec.setType(CosmosVectorIndexType.DISK_ANN.toString());
        indexingPolicy.setVectorIndexes(Arrays.asList(cosmosVectorIndexSpec));
        collectionDefinition.setIndexingPolicy(indexingPolicy);

        //create container
        ThroughputProperties throughputProperties = ThroughputProperties.createManualThroughput(400);
        client.createDatabaseIfNotExists(databaseName).block();
        CosmosAsyncDatabase database = client.getDatabase(databaseName);
        CosmosContainerResponse containerResponse = database.createContainerIfNotExists(collectionDefinition, throughputProperties).block();
    }

    public List<CosmosEntity> loadFromJsonFile(String filePath) {
        var reader = new ObjectMapper().reader();
        try {
            int dimensions = 0;
            var data = reader.readValue(new File(filePath), VectorStoreData.class);
            List<CosmosEntity> list = new ArrayList<CosmosEntity>(data.store.values());
            List<CosmosEntity> cosmosEntities = new ArrayList<>();
            try {
                createVectorIndex(100, dimensions, "COS");
                cosmosEntityRepository.saveAll(list);
            } catch (Exception e) {
                log.warning("Failed to insertAll documents to Cosmos DB NoSQL API, attempting individual upserts: "+ e.getMessage());
                for (CosmosEntity cosmosEntity : list) {
                    log.info("Saving document {} to Cosmos DB NoSQL API" + cosmosEntity.getId());
                    try {
                        cosmosEntityRepository.save(cosmosEntity);
                    } catch (Exception ex) {
                        log.warning("Failed to upsert document "+ cosmosEntity.getId()+ "to Cosmos DB:" + ex);
                    }
                }
            }
            return cosmosEntities;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
    private static class VectorStoreData {
        public Map<String, CosmosEntity> getStore() {
            return store;
        }
        public void setStore(Map<String, CosmosEntity> store) {
            this.store = store;
        }
        private Map<String, CosmosEntity> store = new ConcurrentHashMap<>();
    }
}
