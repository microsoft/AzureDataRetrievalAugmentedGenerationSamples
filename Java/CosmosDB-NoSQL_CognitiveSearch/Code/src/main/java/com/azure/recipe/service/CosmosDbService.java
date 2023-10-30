package com.azure.recipe.service;

import com.azure.cosmos.*;
import com.azure.cosmos.models.*;
import com.azure.cosmos.util.CosmosPagedFlux;
import com.azure.cosmos.util.CosmosPagedIterable;
import com.azure.recipe.model.Recipe;
import lombok.extern.slf4j.Slf4j;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

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

        CosmosAsyncDatabase database = cosmosAsyncClient.getDatabase(databaseName);

        this.container = database.getContainer(containerName);
    }

    private void deleteAllItems() {
        SqlQuerySpec query = new SqlQuerySpec("SELECT * FROM c ");

        CosmosPagedFlux<Recipe> recipeCosmosPagedFlux = container.queryItems(query, new CosmosQueryRequestOptions(), Recipe.class);
        recipeCosmosPagedFlux.flatMap(recipe -> {
            log.info("Recipe: {}", recipe);
            return container.deleteItem(recipe, new CosmosItemRequestOptions());
        }).blockLast();
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

    public List<Recipe> getRecipes(List<String> ids) {
        String join = "'" + String.join("','", ids) + "'";
        String querystring = "SELECT * FROM c WHERE c.id IN(" + join + ")";

        log.info(querystring);

        SqlQuerySpec query = new SqlQuerySpec(querystring);

        CosmosPagedFlux<Recipe> recipeCosmosPagedFlux = container
                .queryItems(query, new CosmosQueryRequestOptions(), Recipe.class);
        return recipeCosmosPagedFlux.collectList().block();
    }

    public List<Recipe> getRecipesToVectorize() {
        SqlQuerySpec query = new SqlQuerySpec("SELECT * FROM c WHERE IS_ARRAY(c.embedding)=false");

        CosmosPagedFlux<Recipe> recipeCosmosPagedFlux = container
                .queryItems(query, new CosmosQueryRequestOptions(), Recipe.class);
        return recipeCosmosPagedFlux.collectList().block();
    }


    public void updateRecipesAsync(Map<String, List<Double>> dictInput) {
        List<CosmosItemOperation> itemOperations = dictInput
                .entrySet()
                .stream()
                .map(s -> {
                    return CosmosBulkOperations.getPatchItemOperation(s.getKey(),
                            new PartitionKey(s.getKey()),
                            CosmosPatchOperations.create()
                                    .add("/embedding", s.getValue())
                    );
                })
                .collect(Collectors.toList());
        container.executeBulkOperations(Flux.fromIterable(itemOperations)).blockLast();

    }

}
