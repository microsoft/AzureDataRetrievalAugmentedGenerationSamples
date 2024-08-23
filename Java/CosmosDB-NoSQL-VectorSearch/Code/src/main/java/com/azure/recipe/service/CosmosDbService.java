package com.azure.recipe.service;

import com.azure.cosmos.*;
import com.azure.cosmos.implementation.guava25.collect.ImmutableList;
import com.azure.cosmos.models.*;
import com.azure.recipe.model.Recipe;
import lombok.extern.slf4j.Slf4j;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.stream.Collectors;

@Slf4j
public class CosmosDbService {

    CosmosAsyncContainer container;

    public CosmosDbService(String endpoint, String key, String databaseName, String containerName) {

        CosmosAsyncClient cosmosAsyncClient = new CosmosClientBuilder()
                .endpoint(endpoint)
                .key(key)
                .consistencyLevel(ConsistencyLevel.EVENTUAL)
                .contentResponseOnWriteEnabled(true)
                .buildAsyncClient();


        CosmosContainerProperties collectionDefinition = new CosmosContainerProperties(containerName, "/id");

        //set vector embedding policy
        CosmosVectorEmbeddingPolicy cosmosVectorEmbeddingPolicy = new CosmosVectorEmbeddingPolicy();
        CosmosVectorEmbedding embedding = new CosmosVectorEmbedding();
        embedding.setPath("/embedding");
        embedding.setDataType(CosmosVectorDataType.FLOAT32);
        embedding.setDimensions(8L);
        embedding.setDistanceFunction(CosmosVectorDistanceFunction.COSINE);
        cosmosVectorEmbeddingPolicy.setCosmosVectorEmbeddings(Arrays.asList(embedding));
        collectionDefinition.setVectorEmbeddingPolicy(cosmosVectorEmbeddingPolicy);

        //set vector indexing policy
        IndexingPolicy indexingPolicy = new IndexingPolicy();
        indexingPolicy.setIndexingMode(IndexingMode.CONSISTENT);
        ExcludedPath excludedPath = new ExcludedPath("/*");
        indexingPolicy.setExcludedPaths(Collections.singletonList(excludedPath));
        IncludedPath includedPath1 = new IncludedPath("/name/?");
        IncludedPath includedPath2 = new IncludedPath("/description/?");
        indexingPolicy.setIncludedPaths(ImmutableList.of(includedPath1, includedPath2));
        CosmosVectorIndexSpec cosmosVectorIndexSpec = new CosmosVectorIndexSpec();
        cosmosVectorIndexSpec.setPath("/embedding");
        cosmosVectorIndexSpec.setType(CosmosVectorIndexType.DISK_ANN.toString());
        indexingPolicy.setVectorIndexes(List.of(cosmosVectorIndexSpec));
        collectionDefinition.setIndexingPolicy(indexingPolicy);

        //create container
        ThroughputProperties throughputProperties = ThroughputProperties.createManualThroughput(400);
        CosmosAsyncDatabase database = cosmosAsyncClient.getDatabase(databaseName);
        CosmosContainerResponse containerResponse = database.createContainerIfNotExists(collectionDefinition, throughputProperties).block();
        this.container = database.getContainer(containerResponse.getProperties().getId());
    }

    public int getRecipeCount(boolean withEmbedding) {
        List<SqlParameter> parameters = List.of(new SqlParameter("@status", withEmbedding));
        SqlQuerySpec query = new SqlQuerySpec("SELECT value Count(c.id) FROM c WHERE IS_ARRAY(c.embedding)=@status", parameters);

        CosmosQueryRequestOptions options = new CosmosQueryRequestOptions();
        List<Integer> results = container.queryItems(query, options, Integer.class).collectList().block();
        return results.get(0);
    }

    public void uploadRecipes(List<Recipe> recipes) {
        List<CosmosItemOperation> itemOperations = recipes
                .stream()
                .map(recipe -> {
                            if (Objects.isNull(recipe.getId())) {
                                recipe.setId(recipe.getName().replace(" ", ""));
                            }
                            return CosmosBulkOperations
                                    .getCreateItemOperation(recipe,
                                            new PartitionKey(recipe.getId()));
                        }
                ).collect(Collectors.toList());

        Flux<CosmosBulkOperationResponse<Object>> cosmosBulkOperationResponseFlux =
                container.executeBulkOperations(Flux.fromIterable(itemOperations));
        cosmosBulkOperationResponseFlux.blockLast();
    }

    public Iterable<Recipe> vectorSearch(List<Double> vector) {
        ArrayList<SqlParameter> paramList = new ArrayList<SqlParameter>();
        paramList.add(new SqlParameter("@embedding", vector.stream().map(aDouble -> (Float) (float) aDouble.doubleValue()).toList().toArray()));
        SqlQuerySpec querySpec = new SqlQuerySpec("SELECT TOP 3 c.name, c.description, c.cuisine, c.difficulty, c.prepTime, c.cookTime, c.totalTime, c.servings, c.ingredients, c.instructions,  VectorDistance(c.embedding,@embedding) AS SimilarityScore   FROM c ORDER BY VectorDistance(c.embedding,@embedding)", paramList);
        ArrayList<Recipe> filteredRecipes = (ArrayList<Recipe>) container.queryItems(querySpec, new CosmosQueryRequestOptions(), Recipe.class).collectList().block();
        return filteredRecipes;
    }
}
